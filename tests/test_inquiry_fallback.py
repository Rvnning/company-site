"""문의 접수 실패 우회 테스트.

Supabase와 Resend는 모두 mock이다. 실제 메일 발송이나 운영 DB 접속을 하지 않는다.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("RESEND_API_KEY", "re_test_disabled")
os.environ.setdefault("MAIL_USERNAME", "staff@example.com")

import httpx

import app as app_module


class InquiryFallbackTests(unittest.TestCase):
    def setUp(self):
        self.flask_app = app_module.app
        self.flask_app.config["TESTING"] = True
        self.flask_app.config["WTF_CSRF_ENABLED"] = False
        previous_limiter = app_module.limiter.enabled
        app_module.limiter.enabled = False
        self.addCleanup(lambda: setattr(app_module.limiter, "enabled", previous_limiter))

        self.client = self.flask_app.test_client()
        self.form = {
            "company_name": "테스트회사",
            "manager_name": "홍길동",
            "phone": "010-0000-0000",
            "email": "visitor@example.com",
            "content": "지붕 임대 문의입니다.",
        }

        self.table_patcher = patch.object(app_module.supabase, "table")
        self.send_patcher = patch.object(
            app_module.resend.Emails,
            "send",
            return_value={"id": "email_test"},
        )
        self.table = self.table_patcher.start()
        self.send = self.send_patcher.start()
        self.addCleanup(self.table_patcher.stop)
        self.addCleanup(self.send_patcher.stop)
        self.table.return_value.insert.return_value.execute.return_value.data = [{"id": 1}]

    def _post(self):
        return self.client.post("/inquiry", data=self.form)

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return list(sess.get("_flashes", []))

    def _fail_db(self):
        self.table.return_value.insert.return_value.execute.side_effect = httpx.ConnectError(
            "[Errno -2] Name or service not known"
        )

    def test_db_down_still_emails_staff_and_flashes_success(self):
        self._fail_db()

        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.send.assert_called_once()
        params = self.send.call_args.args[0]
        self.assertEqual(params["to"], ["staff@example.com"])
        self.assertNotIn("visitor@example.com", params["to"])
        self.assertTrue(params["subject"].startswith("[DB 저장 실패]"))
        self.assertIn("테스트회사", params["subject"])
        for snippet in ("테스트회사", "홍길동", "010-0000-0000", "visitor@example.com", "지붕 임대 문의입니다.", "DB 저장 실패", "데이터베이스에 저장되지 않았습니다"):
            self.assertIn(snippet, params["html"])

        category, message = self._flashes()[0]
        self.assertEqual(category, "success")
        self.assertIn("성공적으로 접수", message)
        self.assertTrue(any("문의 DB 저장 실패" in line for line in logs.output))
        self.table.assert_called_with("inquiries")

    def test_db_and_email_failure_flashes_failure_with_alternate_contact(self):
        self._fail_db()
        self.send.side_effect = RuntimeError("mocked resend outage")

        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.send.assert_called_once()
        params = self.send.call_args.args[0]
        self.assertEqual(params["to"], ["staff@example.com"])
        self.assertIn("지붕 임대 문의입니다.", params["html"])

        flashes = self._flashes()
        self.assertEqual(len(flashes), 1)
        category, message = flashes[0]
        self.assertEqual(category, "danger")
        self.assertIn("실패", message)
        self.assertIn(app_module.INQUIRY_FALLBACK_CONTACT, message)

        logged = "\n".join(logs.output)
        self.assertIn("문의 유실", logged)
        self.assertIn("테스트회사", logged)
        self.assertIn("지붕 임대 문의입니다.", logged)
        self.assertIn("문의 알림 이메일 발송 실패", logged)

    def test_normal_path_saves_and_notifies_without_db_failure_mark(self):
        with self.assertNoLogs(self.flask_app.logger, level="ERROR"):
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.table.assert_called_once_with("inquiries")
        inserted = self.table.return_value.insert.call_args.args[0]
        self.assertEqual(inserted["company_name"], "테스트회사")
        self.assertEqual(inserted["manager_name"], "홍길동")
        self.assertEqual(inserted["phone"], "010-0000-0000")
        self.assertEqual(inserted["email"], "visitor@example.com")
        self.assertEqual(inserted["content"], "지붕 임대 문의입니다.")

        self.send.assert_called_once()
        params = self.send.call_args.args[0]
        self.assertEqual(params["to"], ["staff@example.com"])
        self.assertNotIn("DB 저장 실패", params["subject"])
        self.assertNotIn("DB 저장 실패", params["html"])
        self.assertIn("테스트회사", params["html"])
        self.assertIn("지붕 임대 문의입니다.", params["html"])

        flashes = self._flashes()
        self.assertEqual(len(flashes), 1)
        category, message = flashes[0]
        self.assertEqual(category, "success")
        self.assertIn("성공적으로 접수", message)

    def test_saved_inquiry_still_shows_success_when_notification_fails(self):
        self.send.side_effect = RuntimeError("mocked resend outage")

        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.table.return_value.insert.return_value.execute.assert_called_once()
        category, message = self._flashes()[0]
        self.assertEqual(category, "success")
        self.assertIn("성공적으로 접수", message)
        self.assertTrue(any("문의 알림 이메일 발송 실패" in line for line in logs.output))
        self.assertFalse(any("문의 유실" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
