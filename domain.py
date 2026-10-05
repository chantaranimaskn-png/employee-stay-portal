from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable


def approval_type(approval_no: str) -> str:
    value = (approval_no or "").strip().upper()
    if value.startswith("SA"):
        return "SA"
    if value.startswith("BT"):
        return "BT"
    return ""


def parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def iter_dates(start, end) -> list[date]:
    first = parse_date(start)
    last = parse_date(end)
    if last < first:
        return []
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def periods_overlap(start_a, end_a, start_b, end_b) -> bool:
    return max(parse_date(start_a), parse_date(start_b)) <= min(parse_date(end_a), parse_date(end_b))


def validate_submission(payload: dict, hotels: Iterable[dict], submissions: Iterable[dict]) -> list[str]:
    errors: list[str] = []
    number = (payload.get("approval_no") or "").strip().upper()
    kind = approval_type(number)
    if not kind:
        errors.append("เลขที่อนุมัติต้องขึ้นต้นด้วย SA หรือ BT")

    start = parse_date(payload["start_date"])
    end = parse_date(payload["end_date"])
    if end < start:
        errors.append("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")
    if kind == "SA" and start != end:
        errors.append("เลข SA ต้องมีวันที่เริ่มต้นและสิ้นสุดเป็นวันเดียวกัน")

    for field, label in [
        ("employee_id", "รหัสพนักงาน"),
        ("employee_name", "ชื่อพนักงาน"),
        ("home_branch", "สาขาที่ประจำ"),
        ("support_branch", "สาขาที่เข้าช่วยเหลือ"),
        ("hotel_id", "โรงแรม"),
        ("room_no", "เลขห้อง"),
    ]:
        if not str(payload.get(field, "")).strip():
            errors.append(f"กรุณาระบุ{label}")

    active_hotels = {str(h.get("id")) for h in hotels if h.get("active", True)}
    if payload.get("hotel_id") and str(payload.get("hotel_id")) not in active_hotels:
        errors.append("โรงแรมที่เลือกไม่อยู่ในรายการที่เปิดใช้งาน")

    fingerprint = (
        number,
        str(payload.get("employee_id", "")).strip(),
        str(start),
        str(end),
        str(payload.get("hotel_id", "")),
        str(payload.get("room_no", "")).strip(),
    )
    for item in submissions:
        existing = (
            str(item.get("approval_no", "")).strip().upper(),
            str(item.get("employee_id", "")).strip(),
            str(item.get("start_date", "")),
            str(item.get("end_date", "")),
            str(item.get("hotel_id", "")),
            str(item.get("room_no", "")).strip(),
        )
        if existing == fingerprint and item.get("status") != "ยกเลิก":
            errors.append("พบรายการซ้ำของพนักงาน ช่วงวันที่ โรงแรม และห้องเดียวกัน")
            break
    return errors


def rate_check(claim_type: str, nightly_rate: float, rate_limit: float | None, approval_attached: bool) -> tuple[str, str]:
    actual = float(nightly_rate or 0)
    if actual <= 0:
        return "ไม่ครบ", "กรุณาระบุราคาห้องต่อคืน"

    if claim_type == "SA":
        limit = 600.0
    else:
        if rate_limit is None or float(rate_limit or 0) <= 0:
            return "ไม่ครบ", "BT ต้องระบุเพดานเบิกตามตำแหน่ง"
        limit = float(rate_limit)

    if actual > limit and not approval_attached:
        return "รอ Mail อนุมัติ", f"ราคา {actual:,.2f} บาท เกินเพดาน {limit:,.2f} บาท"
    if actual > limit:
        return "ผ่านแบบมีอนุมัติ", f"เกินเพดาน {limit:,.2f} บาท และมีเอกสารอนุมัติ"
    return "ผ่าน", f"ไม่เกินเพดาน {limit:,.2f} บาท"


def submission_covers(submission: dict, start, end) -> bool:
    return parse_date(submission["start_date"]) <= parse_date(start) and parse_date(submission["end_date"]) >= parse_date(end)


def validate_room_claim(payload: dict, submissions: Iterable[dict], receipt_ids: set[str]) -> list[str]:
    errors: list[str] = []
    occupants = list(payload.get("occupant_submission_ids") or [])
    if not occupants:
        errors.append("กรุณาเลือกพนักงานที่เข้าพัก")
    if len(occupants) > 2:
        errors.append("หนึ่งห้องเลือกพนักงานได้ไม่เกิน 2 คน")
    if payload.get("main_submission_id") not in occupants:
        errors.append("ผู้เบิกหลักต้องเป็นหนึ่งในพนักงานที่เข้าพัก")
    if len(occupants) == 1 and not str(payload.get("solo_reason", "")).strip():
        errors.append("พักคนเดียวต้องระบุเหตุผล")
    if not str(payload.get("room_no", "")).strip():
        errors.append("กรุณาระบุเลขห้อง")
    if payload.get("receipt_id") not in receipt_ids:
        errors.append("กรุณาเลือกใบเสร็จ")

    selected = {str(x.get("id")): x for x in submissions if str(x.get("id")) in occupants}
    for sid in occupants:
        item = selected.get(str(sid))
        if not item:
            errors.append("ไม่พบข้อมูลการเข้าพักของพนักงานที่เลือก")
            continue
        if item.get("approval_type") != payload.get("claim_type"):
            errors.append("ไม่สามารถรวมรายการ SA และ BT ในห้องเดียวกัน")
        if str(item.get("hotel_id")) != str(payload.get("hotel_id")):
            errors.append("พนักงานที่เลือกต้องอยู่โรงแรมเดียวกับรายการห้อง")
        if not submission_covers(item, payload["start_date"], payload["end_date"]):
            errors.append(f"ช่วงวันที่ของ {item.get('employee_name')} ไม่ครอบคลุมช่วงห้องพัก")
    return list(dict.fromkeys(errors))


def room_night_count(start, end) -> int:
    return len(iter_dates(start, end))

