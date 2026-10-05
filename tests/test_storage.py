import unittest
from unittest.mock import Mock, patch

import storage


class StorageTests(unittest.TestCase):
    def test_load_supabase_rebuilds_state(self):
        response = Mock()
        response.json.return_value = [
            {"collection": "hotels", "record_id": "h1", "payload": {"id": "h1", "name": "Hotel A"}},
            {"collection": "settings", "record_id": "singleton", "payload": {"support_branches": ["B1"]}},
        ]
        response.raise_for_status.return_value = None
        config = {"url": "https://example.supabase.co", "key": "secret", "bucket": "stay-files"}
        with patch("storage.requests.get", return_value=response) as request:
            state = storage._load_supabase(config)
        self.assertEqual(state["hotels"][0]["name"], "Hotel A")
        self.assertEqual(state["settings"]["support_branches"], ["B1"])
        request.assert_called_once()

    def test_save_supabase_upserts_records(self):
        response = Mock()
        response.raise_for_status.return_value = None
        config = {"url": "https://example.supabase.co", "key": "secret", "bucket": "stay-files"}
        state = storage._normalize_state({"hotels": [{"id": "h1", "name": "Hotel A"}]})
        with patch("storage.requests.post", return_value=response) as request:
            storage._save_supabase(state, config)
        payload = request.call_args.kwargs["json"]
        self.assertTrue(any(row["collection"] == "hotels" and row["record_id"] == "h1" for row in payload))
        self.assertTrue(any(row["collection"] == "settings" for row in payload))


if __name__ == "__main__":
    unittest.main()
