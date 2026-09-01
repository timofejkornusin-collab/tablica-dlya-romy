#!/usr/bin/env python3
"""Live POST routes through production_students_safety with a crashing orig_post."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
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


class SafetyLivePostTest(unittest.TestCase):
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
        def crashing_post(_self):
            raise RuntimeError("production post boom")

        server.Handler.do_POST = crashing_post
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
        server.save_data = self._real_save
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _json(self, path: str, payload: dict, method: str = "POST"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=body,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = {"raw": raw[:500].decode("utf-8", "replace")}
            return exc.code, data

    def test_create_table_upload_and_delete_return_json(self) -> None:
        status, created = self._json(
            "/api/students",
            {
                "name": "рома-тест",
                "grade": "10",
                "template": "once",
                "startDate": "2026-09-03",
                "slots": [{"weekday": 3, "time": "16:00"}],
            },
        )
        self.assertEqual(status, 200, created)
        self.assertTrue(created.get("ok"))
        self.assertEqual(created["student"]["grade"], "10")
        student_id = created["student"]["id"]
        self.assertTrue(created["student"]["rows"])

        row = dict(created["student"]["rows"][0])
        row["topic"] = "Вводный урок"
        row["bankId"] = ""
        row["importedSource"] = "manual:"
        status, saved = self._json(
            "/api/table",
            {"id": student_id, "template": "once", "rows": [row]},
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["student"]["rows"][0]["topic"], "Вводный урок")

        boundary = "----JournalTestBoundary"
        pdf = b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"studentId\"\r\n\r\n{student_id}\r\n".encode("utf-8"),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"row\"\r\n\r\n0\r\n".encode("utf-8"),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"field\"\r\n\r\npractice\r\n".encode("utf-8"),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"mini.pdf\"\r\n"
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8")
            + pdf
            + b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        upload_body = b"".join(chunks)
        req = urllib.request.Request(
            self._url("/api/upload"),
            data=upload_body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            uploaded = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(resp.status, 200)
        self.assertTrue(uploaded.get("ok"), uploaded)
        self.assertTrue(uploaded.get("needsImport"))
        self.assertTrue(uploaded["student"]["rows"][0]["practiceFileId"])

        status, deleted = self._json("/api/students/delete", {"id": student_id})
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted.get("ok"))
        remaining = json.loads(self.data_file.read_text(encoding="utf-8"))
        self.assertEqual(remaining.get("students"), [])
