from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from domain import room_night_count


def _hotel_map(state: dict) -> dict:
    return {str(x.get("id")): x.get("name", "") for x in state.get("hotels", [])}


def build_export(state: dict, claim_type: str = "ทั้งหมด") -> bytes:
    hotels = _hotel_map(state)
    submissions = list(state.get("submissions", []))
    receipts = list(state.get("receipts", []))
    claims = list(state.get("room_claims", []))
    if claim_type in {"SA", "BT"}:
        submissions = [x for x in submissions if x.get("approval_type") == claim_type]
        receipts = [x for x in receipts if x.get("claim_type") == claim_type]
        claims = [x for x in claims if x.get("claim_type") == claim_type]

    sub_by_id = {str(x.get("id")): x for x in state.get("submissions", [])}
    receipt_by_id = {str(x.get("id")): x for x in state.get("receipts", [])}

    submission_rows = []
    for x in submissions:
        submission_rows.append({
            "ประเภท": x.get("approval_type"),
            "เลขที่ SA/BT": x.get("approval_no"),
            "วันที่เริ่มต้น": x.get("start_date"),
            "วันที่สิ้นสุด": x.get("end_date"),
            "รหัสพนักงาน": x.get("employee_id"),
            "ชื่อพนักงาน": x.get("employee_name"),
            "สาขาที่ประจำ": x.get("home_branch"),
            "สาขาที่เข้าช่วยเหลือ": x.get("support_branch"),
            "โรงแรม": hotels.get(str(x.get("hotel_id")), x.get("hotel_name", "")),
            "เลขห้อง": x.get("room_no"),
            "สถานะ": x.get("status"),
            "หมายเหตุ": x.get("note", ""),
        })

    receipt_rows = []
    for x in receipts:
        receipt_rows.append({
            "ประเภท": x.get("claim_type"),
            "เลขที่ใบเสร็จ": x.get("receipt_no"),
            "วันที่ใบเสร็จ": x.get("receipt_date"),
            "โรงแรม": hotels.get(str(x.get("hotel_id")), ""),
            "ยอดใบเสร็จรวม VAT": float(x.get("gross_amount", 0) or 0),
            "รูปแบบ VAT": x.get("vat_mode"),
            "หมายเหตุ": x.get("note", ""),
        })

    claim_rows = []
    for x in claims:
        occupants = [sub_by_id.get(str(sid), {}) for sid in x.get("occupant_submission_ids", [])]
        main = sub_by_id.get(str(x.get("main_submission_id")), {})
        receipt = receipt_by_id.get(str(x.get("receipt_id")), {})
        nights = room_night_count(x.get("start_date"), x.get("end_date"))
        claim_rows.append({
            "ประเภท": x.get("claim_type"),
            "เลขที่ SA/BT": ", ".join(sorted({str(o.get("approval_no")) for o in occupants if o.get("approval_no")})),
            "สาขาที่เข้าช่วยเหลือ": x.get("support_branch"),
            "โรงแรม": hotels.get(str(x.get("hotel_id")), ""),
            "เลขห้อง": x.get("room_no"),
            "วันที่เริ่มต้น": x.get("start_date"),
            "วันที่สิ้นสุด": x.get("end_date"),
            "จำนวนคืน": nights,
            "ผู้เข้าพัก": ", ".join(o.get("employee_name", "") for o in occupants),
            "ผู้เบิกหลัก": main.get("employee_name", ""),
            "ราคาต่อคืนรวม VAT": float(x.get("nightly_rate", 0) or 0),
            "ยอดห้องรวม": float(x.get("nightly_rate", 0) or 0) * nights,
            "เพดานเบิก": 600.0 if x.get("claim_type") == "SA" else float(x.get("rate_limit", 0) or 0),
            "ผลตรวจเรท": x.get("rate_status"),
            "เลขที่ใบเสร็จ": receipt.get("receipt_no", ""),
            "ยอดใบเสร็จ": float(receipt.get("gross_amount", 0) or 0),
            "เหตุผลพักเดี่ยว": x.get("solo_reason", ""),
            "หมายเหตุ": x.get("note", ""),
        })

    bt_numbers = sorted({x.get("approval_no") for x in submissions if x.get("approval_type") == "BT" and x.get("approval_no")})
    bt_rows = [{"*หมายเลขการทำ BT\nกรุณาระบุหมายเลขการทำ BT ที่คุณต้องการเบิก โดยแต่ละหมายเลขควรอยู่ในบรรทัดแยกกัน สูงสุด 2000 บรรทัด": x} for x in bt_numbers]

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(submission_rows).to_excel(writer, sheet_name="ข้อมูลพนักงาน", index=False)
        pd.DataFrame(claim_rows).to_excel(writer, sheet_name="สรุปห้องพัก", index=False)
        pd.DataFrame(receipt_rows).to_excel(writer, sheet_name="ใบเสร็จ", index=False)
        pd.DataFrame(bt_rows).to_excel(writer, sheet_name="BT_Form_Input", index=False)
        workbook = writer.book
        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            sheet.sheet_view.showGridLines = False
            for cell in sheet[1]:
                cell.font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
                cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            for col in sheet.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=10)
                sheet.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 36)
            sheet.row_dimensions[1].height = 42 if sheet.title == "BT_Form_Input" else 28
    return output.getvalue()

