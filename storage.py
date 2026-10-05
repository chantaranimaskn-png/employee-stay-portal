from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
DB_PATH = DATA_DIR / "database.json"

DEFAULT_STATE = {
    "employees": [],
    "hotels": [],
    "submissions": [],
    "receipts": [],
    "room_claims": [],
    "settings": {"support_branches": []},
}

COLLECTIONS = ("employees", "hotels", "submissions", "receipts", "room_claims")


def _supabase_config() -> dict | None:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "stay-files").strip() or "stay-files"
    try:
        import streamlit as st

        config = st.secrets.get("supabase", {})
        url = str(config.get("url", url)).strip()
        key = str(config.get("service_role_key", key)).strip()
        bucket = str(config.get("storage_bucket", bucket)).strip() or "stay-files"
    except Exception:
        pass
    if not url or not key:
        return None
    return {"url": url.rstrip("/"), "key": key, "bucket": bucket}


def _supabase_headers(config: dict, *, content_type: str = "application/json") -> dict:
    return {
        "apikey": config["key"],
        "Authorization": f"Bearer {config['key']}",
        "Content-Type": content_type,
    }


def _normalize_state(loaded: dict) -> dict:
    state = {**DEFAULT_STATE, **loaded}
    for key in COLLECTIONS:
        state[key] = list(state.get(key) or [])
    state["settings"] = {**DEFAULT_STATE["settings"], **(state.get("settings") or {})}
    return state


def _load_supabase(config: dict) -> dict:
    response = requests.get(
        f"{config['url']}/rest/v1/app_records",
        headers=_supabase_headers(config),
        params={"select": "collection,record_id,payload"},
        timeout=30,
    )
    response.raise_for_status()
    loaded = {key: [] for key in COLLECTIONS}
    loaded["settings"] = {}
    for row in response.json():
        collection = row.get("collection")
        payload = row.get("payload") or {}
        if collection in COLLECTIONS:
            loaded[collection].append(payload)
        elif collection == "settings":
            loaded["settings"] = payload
    return _normalize_state(loaded)


def _save_supabase(state: dict, config: dict) -> None:
    rows = []
    for collection in COLLECTIONS:
        for item in state.get(collection, []):
            record_id = str(item.get("id") or item.get("employee_id") or new_id(collection[:3]))
            rows.append({"collection": collection, "record_id": record_id, "payload": item, "updated_at": now_text()})
    rows.append({"collection": "settings", "record_id": "singleton", "payload": state.get("settings", {}), "updated_at": now_text()})
    response = requests.post(
        f"{config['url']}/rest/v1/app_records",
        headers={**_supabase_headers(config), "Prefer": "resolution=merge-duplicates,return=minimal"},
        params={"on_conflict": "collection,record_id"},
        json=rows,
        timeout=30,
    )
    response.raise_for_status()


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    ensure_dirs()
    config = _supabase_config()
    if config:
        return _load_supabase(config)
    if not DB_PATH.exists():
        save_state(DEFAULT_STATE.copy())
    try:
        loaded = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        loaded = {}
    return _normalize_state(loaded)


def save_state(state: dict) -> None:
    ensure_dirs()
    config = _supabase_config()
    if config:
        _save_supabase(state, config)
        return
    handle, temp_name = tempfile.mkstemp(prefix="database_", suffix=".json", dir=str(DATA_DIR))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(temp_name, DB_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def save_upload(uploaded_file, category: str) -> str:
    if uploaded_file is None:
        return ""
    config = _supabase_config()
    safe_name = Path(uploaded_file.name).name
    object_path = f"{category}/{uuid.uuid4().hex[:10]}_{safe_name}"
    if config:
        content_type = getattr(uploaded_file, "type", None) or "application/octet-stream"
        content = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
        response = requests.post(
            f"{config['url']}/storage/v1/object/{quote(config['bucket'], safe='')}/{quote(object_path, safe='/')}",
            headers={**_supabase_headers(config, content_type=content_type), "x-upsert": "false"},
            data=content,
            timeout=60,
        )
        response.raise_for_status()
        return f"supabase://{config['bucket']}/{object_path}"
    target_dir = UPLOAD_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / object_path.split("/", 1)[1]
    with target.open("wb") as out:
        shutil.copyfileobj(uploaded_file, out)
    return str(target.relative_to(BASE_DIR))


def upsert_employee(state: dict, employee_id: str, employee_name: str, home_branch: str) -> None:
    employee_id = employee_id.strip()
    existing = next((x for x in state["employees"] if str(x.get("employee_id")) == employee_id), None)
    if existing:
        existing.update({"employee_name": employee_name.strip(), "home_branch": home_branch.strip(), "updated_at": now_text()})
    else:
        state["employees"].append({
            "id": new_id("emp"),
            "employee_id": employee_id,
            "employee_name": employee_name.strip(),
            "home_branch": home_branch.strip(),
            "updated_at": now_text(),
        })

