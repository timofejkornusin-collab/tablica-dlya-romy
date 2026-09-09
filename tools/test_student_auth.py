#!/usr/bin/env python3
"""Ученик через nginx не должен получать кабинет учителя."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import journal
import server


def load_safety():
    spec = importlib.util.spec_from_file_location(
        "production_students_safety",
        ROOT / "tools" / "production_students_safety.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeHandler:
    def __init__(self, host: str, ip: str, extra: dict | None = None):
        self.client_address = (ip, 443)
        headers = Message()
        if host:
            headers["Host"] = host
        for key, value in (extra or {}).items():
            headers[key] = value
        self.headers = headers


class AllowLocalTeacherTest(unittest.TestCase):
    def test_nginx_host_is_not_teacher(self) -> None:
        handler = FakeHandler("rusklasst.ru", "127.0.0.1")
        self.assertFalse(server.allow_local_teacher(handler))

    def test_forwarded_loopback_is_not_teacher(self) -> None:
        handler = FakeHandler(
            "rusklasst.ru",
            "127.0.0.1",
            {"X-Forwarded-For": "203.0.113.10", "X-Forwarded-Proto": "https"},
        )
        self.assertFalse(server.allow_local_teacher(handler))

    def test_local_app_still_allows_teacher(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INVOCATION_ID", None)
            os.environ.pop("JOURNAL_PUBLIC_URL", None)
            os.environ.pop("JOURNAL_DISABLE_LOCAL_TEACHER", None)
            handler = FakeHandler("127.0.0.1:8765", "127.0.0.1")
            self.assertTrue(server.allow_local_teacher(handler))

    def test_systemd_never_allows_teacher(self) -> None:
        handler = FakeHandler("127.0.0.1:8765", "127.0.0.1")
        with patch.dict(os.environ, {"INVOCATION_ID": "unit"}):
            self.assertFalse(server.allow_local_teacher(handler))


class ProxiedStudentAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self.tmp.name)
        uploads = data_dir / "uploads"
        banks = data_dir / "banks"
        uploads.mkdir()
        banks.mkdir()
        self.data_file = data_dir / "students.json"
        self.auth_file = data_dir / "auth.json"

        self._real_get = server.Handler.do_GET
        self._real_post = server.Handler.do_POST
        self._real_send = server.Handler._send_json
        self._real_read = server.Handler._read_json
        self._real_save = server.save_data
        self._real_session = server.Handler._session_payload
        self._real_user = server.Handler._user
        self._real_tunnel = server.start_tunnel

        self.patches = [
            patch.object(server, "DATA_DIR", data_dir),
            patch.object(server, "DATA_FILE", self.data_file),
            patch.object(server, "AUTH_FILE", self.auth_file),
            patch.object(server, "UPLOADS_DIR", uploads),
            patch.object(journal, "DATA_DIR", data_dir),
            patch.object(journal, "BANKS_DIR", banks),
        ]
        for item in self.patches:
            item.start()

        self.data_file.write_text('{"students": []}\n', encoding="utf-8")
        server.load_auth()
        safety = load_safety()
        self.assertTrue(safety.install(server.__dict__))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
        server.Handler.do_GET = self._real_get
        server.Handler.do_POST = self._real_post
        server.Handler._send_json = self._real_send
        server.Handler._read_json = self._real_read
        server.Handler._session_payload = self._real_session
        server.Handler._user = self._real_user
        server.start_tunnel = self._real_tunnel
        server.save_data = self._real_save
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        hdrs = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            hdrs.update(headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            raw = resp.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {"raw": raw[:500].decode("utf-8", "replace")}
            cookie = resp.getheader("Set-Cookie") or ""
            return resp.status, data, cookie
        finally:
            conn.close()

    def _nginx(self, extra: dict | None = None) -> dict:
        headers = {
            "Host": "rusklasst.ru",
            "X-Forwarded-For": "203.0.113.10",
            "X-Forwarded-Proto": "https",
            "X-Real-IP": "203.0.113.10",
        }
        if extra:
            headers.update(extra)
        return headers

    def test_fresh_site_visit_is_not_teacher(self) -> None:
        status, data, _cookie = self._request("GET", "/api/session", headers=self._nginx())
        self.assertEqual(status, 200, data)
        self.assertIsNone(data.get("user"))
        self.assertFalse(data.get("localTeacher"))
        self.assertEqual(data.get("publicUrl"), "https://rusklasst.ru")

        status, data, _cookie = self._request("GET", "/api/students", headers=self._nginx())
        self.assertEqual(status, 401, data)

        status, created, _cookie = self._request(
            "POST",
            "/api/students",
            {
                "name": "Взлом",
                "grade": "11",
                "startDate": "2026-09-01",
                "slots": [{"weekday": 0, "time": "16:00"}],
                "endDate": "2027-05-27",
            },
            headers=self._nginx(),
        )
        self.assertEqual(status, 401, created)

    def test_student_login_sees_only_own_table(self) -> None:
        status, created, _cookie = self._request(
            "POST",
            "/api/students",
            {
                "name": "Арсений",
                "grade": "11",
                "startDate": "2026-09-01",
                "slots": [{"weekday": 0, "time": "16:00"}],
                "endDate": "2027-05-27",
            },
        )
        self.assertEqual(status, 200, created)
        self.assertTrue(created.get("ok"), created)
        login = created["login"]
        password = created["password"]
        student_id = created["student"]["id"]

        status, other, _cookie = self._request(
            "POST",
            "/api/students",
            {
                "name": "Максим",
                "grade": "11",
                "startDate": "2026-09-01",
                "slots": [{"weekday": 2, "time": "16:00"}],
                "endDate": "2027-05-27",
            },
        )
        self.assertEqual(status, 200, other)

        status, session, cookie = self._request(
            "POST",
            "/api/login",
            {"login": login, "password": password},
            headers=self._nginx(),
        )
        self.assertEqual(status, 200, session)
        self.assertEqual(session.get("user", {}).get("role"), "student")
        self.assertNotEqual(session.get("user", {}).get("role"), "teacher")
        self.assertFalse(session.get("localTeacher"))
        token = ""
        if "journal_session=" in cookie:
            token = cookie.split("journal_session=", 1)[1].split(";", 1)[0]

        status, students, _cookie = self._request(
            "GET",
            "/api/students",
            headers=self._nginx({"Cookie": f"journal_session={token}"}),
        )
        self.assertEqual(status, 200, students)
        names = [item.get("name") for item in students.get("students") or []]
        self.assertEqual(names, ["Арсений"])
        self.assertNotIn("Максим", names)
        self.assertEqual((students.get("students") or [{}])[0].get("id"), student_id)

        status, deleted, _cookie = self._request(
            "POST",
            "/api/students/delete",
            {"id": student_id},
            headers=self._nginx({"Cookie": f"journal_session={token}"}),
        )
        self.assertEqual(status, 403, deleted)


if __name__ == "__main__":
    unittest.main()
