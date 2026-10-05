import unittest

from auth import authenticate, is_locked


class AuthTests(unittest.TestCase):
    def test_default_accounts(self):
        self.assertEqual(authenticate("admin", "area2")["role"], "admin")
        self.assertEqual(authenticate("staff", "123456")["role"], "staff")
        self.assertIsNone(authenticate("staff", "wrong"))

    def test_locked_submission(self):
        self.assertTrue(is_locked({"locked": True, "status": "รอตรวจสอบ"}))
        self.assertTrue(is_locked({"status": "นำไปทำเบิกแล้ว"}))
        self.assertFalse(is_locked({"status": "รอตรวจสอบ"}))


if __name__ == "__main__":
    unittest.main()

