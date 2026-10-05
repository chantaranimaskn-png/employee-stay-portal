import unittest

from domain import approval_type, rate_check, validate_room_claim, validate_submission


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.hotels = [{"id": "h1", "name": "Hotel A", "active": True}]

    def test_approval_type(self):
        self.assertEqual(approval_type("sa123"), "SA")
        self.assertEqual(approval_type("BT999"), "BT")
        self.assertEqual(approval_type("XX1"), "")

    def test_sa_must_be_one_day(self):
        payload = {
            "approval_no": "SA001", "start_date": "2026-10-01", "end_date": "2026-10-02",
            "employee_id": "1", "employee_name": "A", "home_branch": "B1",
            "support_branch": "B2", "hotel_id": "h1", "room_no": "101",
        }
        errors = validate_submission(payload, self.hotels, [])
        self.assertTrue(any("วันเดียวกัน" in value for value in errors))

    def test_bt_can_span_dates(self):
        payload = {
            "approval_no": "BT001", "start_date": "2026-10-01", "end_date": "2026-10-05",
            "employee_id": "1", "employee_name": "A", "home_branch": "B1",
            "support_branch": "B2", "hotel_id": "h1", "room_no": "101",
        }
        self.assertEqual(validate_submission(payload, self.hotels, []), [])

    def test_rate_rules(self):
        self.assertEqual(rate_check("SA", 600, None, False)[0], "ผ่าน")
        self.assertEqual(rate_check("SA", 650, None, False)[0], "รอ Mail อนุมัติ")
        self.assertEqual(rate_check("SA", 650, None, True)[0], "ผ่านแบบมีอนุมัติ")
        self.assertEqual(rate_check("BT", 500, None, False)[0], "ไม่ครบ")
        self.assertEqual(rate_check("BT", 500, 550, False)[0], "ผ่าน")

    def test_room_claim_checks_coverage_and_solo_reason(self):
        submissions = [{
            "id": "s1", "approval_type": "BT", "hotel_id": "h1", "employee_name": "A",
            "start_date": "2026-10-01", "end_date": "2026-10-05",
        }]
        payload = {
            "claim_type": "BT", "hotel_id": "h1", "start_date": "2026-10-01", "end_date": "2026-10-05",
            "occupant_submission_ids": ["s1"], "main_submission_id": "s1", "room_no": "101",
            "receipt_id": "r1", "solo_reason": "",
        }
        errors = validate_room_claim(payload, submissions, {"r1"})
        self.assertTrue(any("พักคนเดียว" in value for value in errors))


if __name__ == "__main__":
    unittest.main()

