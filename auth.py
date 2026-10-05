from __future__ import annotations

import base64
import hashlib
import hmac


DEFAULT_USERS = {
    "admin": {
        "role": "admin",
        "password_hash": "pbkdf2_sha256$260000$stay-admin-v1$jsIYg3ijbYLL0nliCBUCxRBcqOzKhl07W9MSCd5Zhdw=",
    },
    "staff": {
        "role": "staff",
        "password_hash": "pbkdf2_sha256$260000$stay-staff-v1$lk/1g3JVrsl12hEtzesvewJDx6FUMJKg2qV2dfWd/x0=",
    },
}


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(base64.b64encode(actual).decode("ascii"), expected)
    except (TypeError, ValueError):
        return False


def authenticate(username: str, password: str, configured_users: dict | None = None) -> dict | None:
    users = configured_users or DEFAULT_USERS
    normalized = (username or "").strip().lower()
    record = users.get(normalized)
    if not record or not verify_password(password or "", record.get("password_hash", "")):
        return None
    return {"username": normalized, "role": record.get("role", "staff")}


def is_locked(submission: dict) -> bool:
    return bool(submission.get("locked")) or submission.get("status") == "นำไปทำเบิกแล้ว"

