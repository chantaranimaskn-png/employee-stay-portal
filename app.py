from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from auth import authenticate, is_locked
from domain import approval_type, rate_check, validate_room_claim, validate_submission
from export_xlsx import build_export
from storage import load_state, new_id, now_text, save_state, save_upload, upsert_employee


st.set_page_config(page_title="ระบบแจ้งข้อมูลเข้าพัก", page_icon="🏨", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1500px;}
    div[data-testid="stMetric"] {background:#f8fafc; border:1px solid #e2e8f0; padding:14px; border-radius:12px;}
    div[data-testid="stForm"] {border:1px solid #e2e8f0; border-radius:14px; padding:1rem; background:#ffffff;}
    .app-note {padding:12px 14px; border-radius:10px; background:#eff6ff; border-left:4px solid #2563eb;}
    .muted {color:#64748b; font-size:.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def hotel_label(hotel: dict) -> str:
    area = ", ".join(x for x in [hotel.get("district", ""), hotel.get("province", "")] if x)
    return f"{hotel.get('name', '')}{' — ' + area if area else ''}"


def as_dataframe(rows: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame([{label: row.get(key, "") for key, label in columns.items()} for row in rows])


def rerun_saved(message: str) -> None:
    st.session_state["flash_message"] = message
    st.rerun()


def configured_auth_users() -> dict | None:
    try:
        config = st.secrets.get("auth", {})
    except (FileNotFoundError, KeyError):
        return None
    required = ["admin_username", "admin_password_hash", "staff_username", "staff_password_hash"]
    if not all(config.get(key) for key in required):
        return None
    return {
        str(config["admin_username"]).strip().lower(): {"role": "admin", "password_hash": config["admin_password_hash"]},
        str(config["staff_username"]).strip().lower(): {"role": "staff", "password_hash": config["staff_password_hash"]},
    }


def login_page() -> None:
    st.title("เข้าสู่ระบบแจ้งข้อมูลค่าที่พัก")
    st.caption("สำหรับพนักงานผู้กรอกข้อมูลและ Admin ผู้จัดทำเบิก")
    with st.form("login_form"):
        username = st.text_input("ชื่อผู้ใช้")
        password = st.text_input("รหัสผ่าน", type="password")
        submitted = st.form_submit_button("เข้าสู่ระบบ", type="primary", use_container_width=True)
    if submitted:
        user = authenticate(username, password, configured_auth_users())
        if user:
            st.session_state["current_user"] = user
            st.rerun()
        else:
            st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")


state = load_state()
current_user = st.session_state.get("current_user")
if not current_user:
    login_page()
    st.stop()

if message := st.session_state.pop("flash_message", None):
    st.success(message)

with st.sidebar:
    st.title("🏨 Stay Portal")
    role_label = "Admin" if current_user["role"] == "admin" else "พนักงาน"
    st.caption(f"เข้าสู่ระบบ: {current_user['username']} ({role_label})")
    if st.button("ออกจากระบบ", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.caption("ระบบนี้แยกข้อมูลจาก Web app เบิกค่าที่พักเดิม")


def employee_page() -> None:
    st.title("แจ้งข้อมูลการเข้าพัก")
    st.markdown(
        '<div class="app-note">กรอกหนึ่งรายการต่อโรงแรมและเลขห้อง หากเปลี่ยนโรงแรมหรือห้องระหว่างช่วง BT กรุณาส่งรายการใหม่</div>',
        unsafe_allow_html=True,
    )

    active_hotels = [x for x in state["hotels"] if x.get("active", True)]
    if not active_hotels:
        st.warning("Admin ยังไม่ได้เพิ่มรายชื่อโรงแรม จึงยังไม่สามารถส่งแบบฟอร์มได้")
        return

    employee_id = st.text_input("รหัสพนักงาน *", placeholder="เช่น 31889").strip()
    profile = next((x for x in state["employees"] if str(x.get("employee_id")) == employee_id), {})
    if st.session_state.get("profile_employee_id") != employee_id:
        st.session_state["profile_employee_id"] = employee_id
        st.session_state["employee_name_input"] = profile.get("employee_name", "")
        st.session_state["home_branch_input"] = profile.get("home_branch", "")

    approval_no = st.text_input("เลขที่อนุมัติ SA/BT *", placeholder="เช่น SA... หรือ BT...").strip().upper()
    kind = approval_type(approval_no)
    if approval_no and not kind:
        st.error("เลขที่อนุมัติต้องขึ้นต้นด้วย SA หรือ BT")
    elif kind == "SA":
        st.info("SA: วันที่เริ่มต้นและสิ้นสุดต้องเป็นวันเดียวกัน และเพดานปกติ 600 บาทต่อห้อง/คืน รวม VAT")
    elif kind == "BT":
        st.info("BT: เลือกช่วงวันที่เริ่มต้น–สิ้นสุดได้ ส่วนเพดานเบิก Admin จะระบุตามตำแหน่ง")

    with st.form("employee_submission", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            employee_name = st.text_input("ชื่อพนักงาน *", key="employee_name_input")
            home_branch = st.text_input("สาขาที่ประจำ *", key="home_branch_input")
            support_branch = st.text_input("สาขาที่เข้าช่วยเหลือ *")
        with c2:
            hotel_id = st.selectbox(
                "โรงแรมที่เข้าพัก *",
                options=[str(x["id"]) for x in active_hotels],
                format_func=lambda value: hotel_label(next(x for x in active_hotels if str(x["id"]) == value)),
            )
            room_no = st.text_input("เลขห้อง *")
            note = st.text_input("หมายเหตุ (ถ้ามี)")

        d1, d2 = st.columns(2)
        with d1:
            start_date = st.date_input("วันที่เริ่มต้นช่วยเหลือ/เข้าพัก *", value=date.today())
        with d2:
            if kind == "SA":
                end_date = start_date
                st.date_input("วันที่สิ้นสุด *", value=start_date, disabled=True)
            else:
                end_date = st.date_input("วันที่สิ้นสุด *", value=start_date)

        consent = st.checkbox("ยืนยันว่าข้อมูลโรงแรม ห้อง และช่วงวันที่ถูกต้อง")
        submitted = st.form_submit_button("บันทึกข้อมูลการเข้าพัก", type="primary", use_container_width=True)

    if submitted:
        payload = {
            "approval_no": approval_no,
            "approval_type": kind,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "home_branch": home_branch,
            "support_branch": support_branch,
            "hotel_id": hotel_id,
            "room_no": room_no,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "note": note,
        }
        errors = validate_submission(payload, active_hotels, state["submissions"])
        if not consent:
            errors.append("กรุณายืนยันความถูกต้องของข้อมูล")
        if errors:
            for error in errors:
                st.error(error)
        else:
            payload.update({"id": new_id("stay"), "status": "รอตรวจสอบ", "created_at": now_text(), "updated_at": now_text()})
            state["submissions"].append(payload)
            upsert_employee(state, employee_id, employee_name, home_branch)
            save_state(state)
            rerun_saved("บันทึกข้อมูลเรียบร้อยแล้ว ครั้งถัดไประบบจะเติมชื่อและสาขาที่ประจำให้อัตโนมัติ")

    if employee_id:
        recent = [x for x in state["submissions"] if str(x.get("employee_id")) == employee_id][-10:]
        if recent:
            st.subheader("รายการล่าสุดของคุณ")
            st.dataframe(
                as_dataframe(recent, {
                    "approval_no": "เลข SA/BT", "start_date": "เริ่มต้น", "end_date": "สิ้นสุด",
                    "support_branch": "สาขาช่วยเหลือ", "room_no": "ห้อง", "status": "สถานะ",
                }),
                use_container_width=True,
                hide_index=True,
            )


def employee_edit_page() -> None:
    st.title("แก้ไขข้อมูลการเข้าพัก")
    st.markdown(
        '<div class="app-note">แก้ไขได้เฉพาะรายการที่ Admin ยังไม่นำไปทำเบิก เมื่อรายการถูกใช้จัดห้องแล้ว ระบบจะล็อกอัตโนมัติ</div>',
        unsafe_allow_html=True,
    )
    employee_id = st.text_input("รหัสพนักงานของรายการที่ต้องการแก้ไข *", key="edit_employee_id").strip()
    if not employee_id:
        return

    records = [x for x in state["submissions"] if str(x.get("employee_id")) == employee_id]
    if not records:
        st.info("ไม่พบรายการของรหัสพนักงานนี้")
        return

    st.dataframe(
        as_dataframe(records, {
            "approval_no": "เลข SA/BT", "start_date": "เริ่มต้น", "end_date": "สิ้นสุด",
            "support_branch": "สาขาช่วยเหลือ", "room_no": "ห้อง", "status": "สถานะ", "locked": "ล็อกแล้ว",
        }),
        use_container_width=True,
        hide_index=True,
    )
    selected_id = st.selectbox(
        "เลือกรายการ",
        [str(x["id"]) for x in records],
        format_func=lambda value: next(
            f"{x['approval_no']} | {x['start_date']}–{x['end_date']} | ห้อง {x['room_no']} | {x['status']}"
            for x in records if str(x["id"]) == value
        ),
    )
    item = next(x for x in state["submissions"] if str(x["id"]) == selected_id)
    if is_locked(item):
        st.error("รายการนี้ถูก Admin นำไปทำเบิกแล้ว จึงไม่สามารถแก้ไขได้ กรุณาติดต่อ Admin หากพบข้อผิดพลาด")
        return

    hotels = list(state["hotels"])
    hotel_ids = [str(x["id"]) for x in hotels]
    current_hotel = str(item.get("hotel_id", ""))
    hotel_index = hotel_ids.index(current_hotel) if current_hotel in hotel_ids else 0
    with st.form("edit_submission_form"):
        c1, c2 = st.columns(2)
        approval_no = c1.text_input("เลขที่อนุมัติ SA/BT *", value=item.get("approval_no", "")).strip().upper()
        employee_name = c2.text_input("ชื่อพนักงาน *", value=item.get("employee_name", ""))
        c3, c4 = st.columns(2)
        home_branch = c3.text_input("สาขาที่ประจำ *", value=item.get("home_branch", ""))
        support_branch = c4.text_input("สาขาที่เข้าช่วยเหลือ *", value=item.get("support_branch", ""))
        c5, c6 = st.columns(2)
        hotel_id = c5.selectbox("โรงแรมที่เข้าพัก *", hotel_ids, index=hotel_index, format_func=lambda value: hotel_label(next(x for x in hotels if str(x["id"]) == value)))
        room_no = c6.text_input("เลขห้อง *", value=item.get("room_no", ""))
        d1, d2 = st.columns(2)
        start_date = d1.date_input("วันที่เริ่มต้น *", value=date.fromisoformat(item["start_date"]))
        end_date = d2.date_input("วันที่สิ้นสุด *", value=date.fromisoformat(item["end_date"]))
        note = st.text_area("หมายเหตุ", value=item.get("note", ""))
        saved = st.form_submit_button("บันทึกการแก้ไข", type="primary", use_container_width=True)

    if saved:
        payload = {
            "approval_no": approval_no, "approval_type": approval_type(approval_no),
            "employee_id": employee_id, "employee_name": employee_name, "home_branch": home_branch,
            "support_branch": support_branch, "hotel_id": hotel_id, "room_no": room_no,
            "start_date": str(start_date), "end_date": str(end_date), "note": note,
        }
        others = [x for x in state["submissions"] if str(x.get("id")) != selected_id]
        errors = validate_submission(payload, hotels, others)
        if errors:
            for error in errors:
                st.error(error)
        else:
            item.update(payload)
            item.update({"status": "รอตรวจสอบ", "updated_at": now_text(), "edited_by": current_user["username"]})
            upsert_employee(state, employee_id, employee_name, home_branch)
            save_state(state)
            rerun_saved("แก้ไขข้อมูลเรียบร้อยแล้ว และส่งกลับให้ Admin ตรวจสอบอีกครั้ง")


def employee_portal() -> None:
    with st.sidebar:
        section = st.radio("เมนูพนักงาน", ["ส่งข้อมูลใหม่", "แก้ไขข้อมูล"], key="staff_section")
    if section == "ส่งข้อมูลใหม่":
        employee_page()
    else:
        employee_edit_page()


def admin_overview() -> None:
    st.subheader("ภาพรวมงาน")
    pending = sum(x.get("status") == "รอตรวจสอบ" for x in state["submissions"])
    waiting_approval = sum(x.get("rate_status") == "รอ Mail อนุมัติ" for x in state["room_claims"])
    cols = st.columns(4)
    cols[0].metric("ข้อมูลเข้าพักทั้งหมด", len(state["submissions"]))
    cols[1].metric("รอตรวจสอบ", pending)
    cols[2].metric("รายการห้อง", len(state["room_claims"]))
    cols[3].metric("รอ Mail อนุมัติ", waiting_approval)

    unresolved = []
    for claim in state["room_claims"]:
        if claim.get("rate_status") in {"ไม่ครบ", "รอ Mail อนุมัติ"}:
            unresolved.append(claim)
    if unresolved:
        st.warning(f"มี {len(unresolved)} รายการที่ยังทำเบิกไม่ได้ กรุณาตรวจเพดานหรือแนบ Mail อนุมัติ")
    elif state["room_claims"]:
        st.success("รายการห้องที่บันทึกไว้ผ่านการตรวจเรททั้งหมด")
    else:
        st.info("เริ่มจากเพิ่มโรงแรม แล้วให้พนักงานส่งข้อมูลการเข้าพัก")


def admin_hotels() -> None:
    st.subheader("รายชื่อโรงแรมที่พนักงานเลือกได้")
    with st.form("add_hotel", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("ชื่อโรงแรม *")
        district = c2.text_input("อำเภอ/เขต")
        province = c3.text_input("จังหวัด *")
        if st.form_submit_button("เพิ่มโรงแรม", type="primary"):
            if not name.strip() or not province.strip():
                st.error("กรุณาระบุชื่อโรงแรมและจังหวัด")
            elif any(x.get("name", "").strip().lower() == name.strip().lower() and x.get("province", "").strip() == province.strip() for x in state["hotels"]):
                st.error("มีโรงแรมชื่อนี้ในจังหวัดเดียวกันแล้ว")
            else:
                state["hotels"].append({
                    "id": new_id("hotel"), "name": name.strip(), "district": district.strip(),
                    "province": province.strip(), "active": True, "created_at": now_text(),
                })
                save_state(state)
                rerun_saved("เพิ่มโรงแรมเรียบร้อยแล้ว")

    if state["hotels"]:
        st.dataframe(
            as_dataframe(state["hotels"], {"name": "โรงแรม", "district": "อำเภอ/เขต", "province": "จังหวัด", "active": "เปิดใช้งาน"}),
            use_container_width=True,
            hide_index=True,
        )
        hotel_id = st.selectbox("เลือกโรงแรมเพื่อเปลี่ยนสถานะ", [str(x["id"]) for x in state["hotels"]], format_func=lambda v: hotel_label(next(x for x in state["hotels"] if str(x["id"]) == v)))
        selected = next(x for x in state["hotels"] if str(x["id"]) == hotel_id)
        new_active = st.toggle("เปิดให้พนักงานเลือก", value=bool(selected.get("active", True)))
        if st.button("บันทึกสถานะโรงแรม"):
            selected["active"] = new_active
            save_state(state)
            rerun_saved("บันทึกสถานะโรงแรมแล้ว")


def filtered_submissions() -> list[dict]:
    rows = list(state["submissions"])
    f1, f2, f3, f4 = st.columns(4)
    claim_type = f1.selectbox("ประเภท", ["ทั้งหมด", "SA", "BT"], key="sub_filter_type")
    support_options = sorted({x.get("support_branch", "") for x in rows if x.get("support_branch")})
    support = f2.selectbox("สาขาที่เข้าช่วยเหลือ", ["ทั้งหมด"] + support_options, key="sub_filter_support")
    status = f3.selectbox("สถานะ", ["ทั้งหมด", "รอตรวจสอบ", "ตรวจแล้ว", "นำไปทำเบิกแล้ว", "ยกเลิก"], key="sub_filter_status")
    search = f4.text_input("ค้นหาชื่อ/รหัส/เลขอนุมัติ", key="sub_filter_search").strip().lower()
    if claim_type != "ทั้งหมด":
        rows = [x for x in rows if x.get("approval_type") == claim_type]
    if support != "ทั้งหมด":
        rows = [x for x in rows if x.get("support_branch") == support]
    if status != "ทั้งหมด":
        rows = [x for x in rows if x.get("status") == status]
    if search:
        rows = [x for x in rows if search in " ".join(str(x.get(k, "")) for k in ["employee_id", "employee_name", "approval_no"]).lower()]
    return rows


def admin_submissions() -> None:
    st.subheader("ข้อมูลที่พนักงานส่งมา")
    rows = filtered_submissions()
    hotels = {str(x["id"]): x["name"] for x in state["hotels"]}
    table_rows = []
    for x in rows:
        table_rows.append({**x, "hotel": hotels.get(str(x.get("hotel_id")), "")})
    st.caption(f"พบ {len(rows):,} รายการ")
    st.dataframe(
        as_dataframe(table_rows, {
            "approval_type": "ประเภท", "approval_no": "เลข SA/BT", "employee_id": "รหัส",
            "employee_name": "พนักงาน", "home_branch": "สาขาประจำ", "support_branch": "สาขาช่วยเหลือ",
            "hotel": "โรงแรม", "room_no": "ห้อง", "start_date": "เริ่ม", "end_date": "สิ้นสุด", "status": "สถานะ",
        }),
        use_container_width=True,
        hide_index=True,
    )
    if not rows:
        return
    selected_id = st.selectbox(
        "เลือกรายการเพื่อตรวจสอบ",
        [str(x["id"]) for x in rows],
        format_func=lambda v: next(f"{x['employee_name']} | {x['approval_no']} | {x['start_date']}–{x['end_date']}" for x in rows if str(x["id"]) == v),
    )
    item = next(x for x in state["submissions"] if str(x["id"]) == selected_id)
    with st.form("review_submission"):
        c1, c2 = st.columns(2)
        new_room = c1.text_input("เลขห้อง", value=item.get("room_no", ""))
        new_status = c2.selectbox("สถานะ", ["รอตรวจสอบ", "ตรวจแล้ว", "นำไปทำเบิกแล้ว", "ยกเลิก"], index=["รอตรวจสอบ", "ตรวจแล้ว", "นำไปทำเบิกแล้ว", "ยกเลิก"].index(item.get("status", "รอตรวจสอบ")))
        allow_staff_edit = st.checkbox("อนุญาตให้พนักงานแก้ไขรายการนี้", value=not is_locked(item))
        admin_note = st.text_area("หมายเหตุ Admin", value=item.get("admin_note", ""))
        if st.form_submit_button("บันทึกผลตรวจ", type="primary"):
            locked = new_status == "นำไปทำเบิกแล้ว" or not allow_staff_edit
            item.update({
                "room_no": new_room.strip(), "status": new_status, "admin_note": admin_note.strip(),
                "locked": locked, "updated_at": now_text(), "reviewed_by": current_user["username"],
            })
            if locked:
                item["locked_at"] = item.get("locked_at") or now_text()
            else:
                item.pop("locked_at", None)
            save_state(state)
            rerun_saved("บันทึกผลตรวจสอบแล้ว")


def admin_receipts() -> None:
    st.subheader("ใบเสร็จจากผู้ให้บริการที่พัก")
    active_hotels = [x for x in state["hotels"] if x.get("active", True)]
    if not active_hotels:
        st.info("กรุณาเพิ่มโรงแรมก่อนบันทึกใบเสร็จ")
        return
    with st.form("add_receipt", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        claim_type = c1.selectbox("ประเภทการเบิก *", ["SA", "BT"])
        hotel_id = c2.selectbox("โรงแรม *", [str(x["id"]) for x in active_hotels], format_func=lambda v: hotel_label(next(x for x in active_hotels if str(x["id"]) == v)))
        receipt_no = c3.text_input("เลขที่ใบเสร็จ *")
        c4, c5, c6 = st.columns(3)
        receipt_date = c4.date_input("วันที่ใบเสร็จ")
        gross_amount = c5.number_input("ยอดใบเสร็จรวม VAT (บาท) *", min_value=0.0, step=50.0)
        vat_mode = c6.selectbox("ภาษี", ["รวม VAT", "ไม่มี VAT"])
        receipt_file = st.file_uploader("แนบใบเสร็จ (PDF/JPG/PNG)", type=["pdf", "jpg", "jpeg", "png"])
        note = st.text_input("หมายเหตุ")
        if st.form_submit_button("บันทึกใบเสร็จ", type="primary"):
            duplicate = any(x.get("receipt_no", "").strip().lower() == receipt_no.strip().lower() and str(x.get("hotel_id")) == hotel_id for x in state["receipts"])
            if not receipt_no.strip() or gross_amount <= 0:
                st.error("กรุณาระบุเลขที่ใบเสร็จและยอดเงิน")
            elif duplicate:
                st.error("เลขที่ใบเสร็จนี้ถูกบันทึกสำหรับโรงแรมแล้ว")
            else:
                state["receipts"].append({
                    "id": new_id("receipt"), "claim_type": claim_type, "hotel_id": hotel_id,
                    "receipt_no": receipt_no.strip(), "receipt_date": str(receipt_date),
                    "gross_amount": float(gross_amount), "vat_mode": vat_mode,
                    "file_path": save_upload(receipt_file, "receipts"), "note": note.strip(), "created_at": now_text(),
                })
                save_state(state)
                rerun_saved("บันทึกใบเสร็จแล้ว")

    hotels = {str(x["id"]): x["name"] for x in state["hotels"]}
    rows = [{**x, "hotel": hotels.get(str(x.get("hotel_id")), "")} for x in state["receipts"]]
    if rows:
        st.dataframe(
            as_dataframe(rows, {"claim_type": "ประเภท", "receipt_no": "เลขที่ใบเสร็จ", "receipt_date": "วันที่", "hotel": "โรงแรม", "gross_amount": "ยอดรวม VAT", "vat_mode": "ภาษี"}),
            use_container_width=True,
            hide_index=True,
        )


def admin_room_claims() -> None:
    st.subheader("จัดห้อง ผู้พักร่วม และราคาเบิก")
    if not state["submissions"]:
        st.info("ยังไม่มีข้อมูลจากพนักงาน")
        return
    if not state["receipts"]:
        st.info("กรุณาบันทึกใบเสร็จก่อนสร้างรายการห้อง")
        return

    f1, f2 = st.columns(2)
    claim_type = f1.selectbox("ประเภทการเบิก", ["SA", "BT"], key="room_claim_type")
    hotel_ids = sorted({str(x.get("hotel_id")) for x in state["submissions"] if x.get("approval_type") == claim_type and x.get("status") != "ยกเลิก"})
    hotel_lookup = {str(x["id"]): x for x in state["hotels"]}
    if not hotel_ids:
        st.warning(f"ยังไม่มีข้อมูลพนักงานประเภท {claim_type}")
        return
    hotel_id = f2.selectbox("โรงแรม", hotel_ids, format_func=lambda v: hotel_label(hotel_lookup.get(v, {"name": v})), key="room_hotel")

    d1, d2 = st.columns(2)
    start_date = d1.date_input("วันที่เริ่มต้นของรายการห้อง", key="room_start")
    end_date = d2.date_input("วันที่สิ้นสุดของรายการห้อง", value=start_date, key="room_end")
    candidates = [
        x for x in state["submissions"]
        if x.get("approval_type") == claim_type and str(x.get("hotel_id")) == hotel_id
        and x.get("status") != "ยกเลิก" and str(x.get("start_date")) <= str(start_date) and str(x.get("end_date")) >= str(end_date)
    ]
    candidate_ids = [str(x["id"]) for x in candidates]
    occupants = st.multiselect(
        "พนักงานที่พักห้องนี้ (สูงสุด 2 คน)",
        candidate_ids,
        format_func=lambda v: next(f"{x['employee_name']} ({x['employee_id']}) | {x['approval_no']} | ห้องที่แจ้ง {x['room_no']}" for x in candidates if str(x["id"]) == v),
        max_selections=2,
    )
    main_id = st.selectbox(
        "ผู้เบิกหลัก",
        occupants or [""],
        format_func=lambda v: "กรุณาเลือกพนักงานก่อน" if not v else next(x["employee_name"] for x in candidates if str(x["id"]) == v),
    )
    valid_receipts = [x for x in state["receipts"] if x.get("claim_type") == claim_type and str(x.get("hotel_id")) == hotel_id]
    receipt_id = st.selectbox(
        "ใบเสร็จที่ใช้อ้างอิง",
        [str(x["id"]) for x in valid_receipts] or [""],
        format_func=lambda v: "ยังไม่มีใบเสร็จที่ตรงกับประเภทและโรงแรม" if not v else next(f"{x['receipt_no']} | {float(x['gross_amount']):,.2f} บาท" for x in valid_receipts if str(x["id"]) == v),
    )

    support_default = candidates[0].get("support_branch", "") if candidates else ""
    room_default = candidates[0].get("room_no", "") if candidates else ""
    with st.form("create_room_claim", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        support_branch = c1.text_input("สาขาที่เข้าช่วยเหลือ", value=support_default)
        room_no = c2.text_input("เลขห้อง *", value=room_default)
        nightly_rate = c3.number_input("ราคาห้องต่อคืนรวม VAT *", min_value=0.0, step=50.0)
        if claim_type == "BT":
            rate_limit_value = st.number_input("เพดานเบิกตามตำแหน่ง (บาท/ห้อง/คืน) *", min_value=0.0, step=50.0)
        else:
            rate_limit_value = 600.0
            st.caption("SA ใช้เพดาน 600 บาทต่อห้อง/คืน รวม VAT")
        solo_reason = st.text_input("เหตุผลพักคนเดียว", disabled=len(occupants) != 1)
        approval_file = st.file_uploader("Mail อนุมัติกรณีเกินเรท", type=["pdf", "jpg", "jpeg", "png", "eml", "msg"])
        note = st.text_area("หมายเหตุ Admin")
        submitted = st.form_submit_button("บันทึกรายการห้อง", type="primary", use_container_width=True)

    if submitted:
        rate_status, rate_message = rate_check(claim_type, nightly_rate, rate_limit_value, approval_file is not None)
        payload = {
            "claim_type": claim_type, "hotel_id": hotel_id, "support_branch": support_branch.strip(),
            "room_no": room_no.strip(), "start_date": str(start_date), "end_date": str(end_date),
            "occupant_submission_ids": occupants, "main_submission_id": main_id,
            "nightly_rate": float(nightly_rate), "rate_limit": float(rate_limit_value),
            "receipt_id": receipt_id, "solo_reason": solo_reason.strip(), "note": note.strip(),
        }
        errors = validate_room_claim(payload, state["submissions"], {str(x["id"]) for x in state["receipts"]})
        if errors:
            for error in errors:
                st.error(error)
        else:
            payload.update({
                "id": new_id("room"), "rate_status": rate_status, "rate_message": rate_message,
                "approval_file": save_upload(approval_file, "approvals"), "created_at": now_text(), "updated_at": now_text(),
            })
            state["room_claims"].append(payload)
            for item in state["submissions"]:
                if str(item.get("id")) in occupants:
                    item.update({
                        "status": "นำไปทำเบิกแล้ว", "locked": True,
                        "locked_at": item.get("locked_at") or now_text(), "locked_by": current_user["username"],
                    })
            save_state(state)
            rerun_saved(f"บันทึกรายการห้องแล้ว — {rate_status}: {rate_message}")

    if state["room_claims"]:
        sub_lookup = {str(x["id"]): x for x in state["submissions"]}
        receipt_lookup = {str(x["id"]): x for x in state["receipts"]}
        rows = []
        for x in state["room_claims"]:
            occ = [sub_lookup.get(str(sid), {}) for sid in x.get("occupant_submission_ids", [])]
            rows.append({
                **x,
                "hotel": hotel_lookup.get(str(x.get("hotel_id")), {}).get("name", ""),
                "occupants": ", ".join(o.get("employee_name", "") for o in occ),
                "receipt": receipt_lookup.get(str(x.get("receipt_id")), {}).get("receipt_no", ""),
            })
        st.divider()
        st.dataframe(
            as_dataframe(rows, {
                "claim_type": "ประเภท", "support_branch": "สาขาช่วยเหลือ", "hotel": "โรงแรม",
                "room_no": "ห้อง", "start_date": "เริ่ม", "end_date": "สิ้นสุด", "occupants": "ผู้เข้าพัก",
                "nightly_rate": "ราคาต่อคืน", "rate_limit": "เพดาน", "rate_status": "ผลตรวจ", "receipt": "ใบเสร็จ",
            }),
            use_container_width=True,
            hide_index=True,
        )


def admin_export() -> None:
    st.subheader("ส่งออกข้อมูลสำหรับทำเบิก")
    claim_type = st.segmented_control("ชุดข้อมูล", ["ทั้งหมด", "SA", "BT"], default="ทั้งหมด")
    export_bytes = build_export(state, claim_type or "ทั้งหมด")
    st.download_button(
        "ดาวน์โหลด Excel สรุป",
        export_bytes,
        file_name=f"stay_claim_{(claim_type or 'all').lower()}_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    bt_numbers = sorted({x.get("approval_no") for x in state["submissions"] if x.get("approval_type") == "BT" and x.get("approval_no")})
    st.text_area("เลข BT สำหรับคัดลอกไป BT_Form (หนึ่งเลขต่อบรรทัด)", value="\n".join(bt_numbers), height=160)
    st.caption("ไฟล์ Excel มี 4 ชีต: ข้อมูลพนักงาน, สรุปห้องพัก, ใบเสร็จ และ BT_Form_Input")


def admin_settings() -> None:
    st.subheader("ตั้งค่าระบบ")
    current = state.get("settings", {})
    with st.form("settings_form"):
        branches = st.text_area("รายชื่อสาขาที่เข้าช่วยเหลือ (หนึ่งสาขาต่อบรรทัด)", value="\n".join(current.get("support_branches", [])))
        if st.form_submit_button("บันทึกการตั้งค่า", type="primary"):
            state["settings"] = {
                "support_branches": [x.strip() for x in branches.splitlines() if x.strip()],
            }
            save_state(state)
            rerun_saved("บันทึกการตั้งค่าแล้ว")
    st.info("บัญชี Admin และ Staff ใช้ระบบล็อกอินแยกกัน รหัสผ่านถูกตรวจด้วยค่าแฮชและไม่ได้เก็บเป็นข้อความปกติ")


def admin_page() -> None:
    st.title("ศูนย์จัดการข้อมูลค่าที่พัก")
    with st.sidebar:
        section = st.radio(
            "เมนู Admin",
            ["ภาพรวม", "โรงแรม", "ข้อมูลเข้าพัก", "ใบเสร็จ", "จัดห้องและราคา", "ส่งออก", "ตั้งค่า"],
            key="admin_section",
        )
    if section == "ภาพรวม":
        admin_overview()
    elif section == "โรงแรม":
        admin_hotels()
    elif section == "ข้อมูลเข้าพัก":
        admin_submissions()
    elif section == "ใบเสร็จ":
        admin_receipts()
    elif section == "จัดห้องและราคา":
        admin_room_claims()
    elif section == "ส่งออก":
        admin_export()
    elif section == "ตั้งค่า":
        admin_settings()


if current_user["role"] == "staff":
    employee_portal()
else:
    admin_page()

