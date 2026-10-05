import unittest
from io import BytesIO

import openpyxl

from export_xlsx import build_export


class ExportTests(unittest.TestCase):
    def test_export_contains_bt_form_input(self):
        state = {
            "employees": [],
            "hotels": [{"id": "h1", "name": "Hotel A"}],
            "submissions": [{
                "id": "s1", "approval_type": "BT", "approval_no": "BT2026001",
                "start_date": "2026-10-01", "end_date": "2026-10-03", "employee_id": "1",
                "employee_name": "A", "home_branch": "B1", "support_branch": "B2",
                "hotel_id": "h1", "room_no": "101", "status": "ตรวจแล้ว",
            }],
            "receipts": [],
            "room_claims": [],
        }
        content = build_export(state, "BT")
        workbook = openpyxl.load_workbook(BytesIO(content), data_only=True)
        self.assertIn("BT_Form_Input", workbook.sheetnames)
        self.assertEqual(workbook["BT_Form_Input"]["A2"].value, "BT2026001")


if __name__ == "__main__":
    unittest.main()

