"""Tests for session_manager module."""

from __future__ import annotations

import json
import tempfile
import unittest


class TestSessionManagerLogEvent(unittest.TestCase):
    """Verify log_event() public method on SessionManager."""

    def test_log_event_exists_and_works(self):
        from session_manager import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.log_event("test_event")
            with open(mgr.session_file) as f:
                lines = f.readlines()
            last = json.loads(lines[-1])
            self.assertEqual(last["type"], "event")
            self.assertEqual(last["event"], "test_event")

    def test_log_event_with_extra(self):
        from session_manager import SessionManager

        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.log_event("custom", {"detail": "foo"})
            with open(mgr.session_file) as f:
                lines = f.readlines()
            last = json.loads(lines[-1])
            self.assertEqual(last["detail"], "foo")


if __name__ == "__main__":
    unittest.main()