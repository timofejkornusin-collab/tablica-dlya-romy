#!/usr/bin/env python3
"""Tests for the CRLF-safe production deploy helper."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_PY = ROOT / "tools" / "deploy-production.py"


def load_deploy():
    spec = importlib.util.spec_from_file_location("deploy_production", DEPLOY_PY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DeployProductionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.stage = self.root / "stage"
        self.app = self.root / "app"
        self.backup = self.root / "backups"
        (self.stage / "static").mkdir(parents=True)
        (self.app / "static").mkdir(parents=True)
        (self.app / "data").mkdir(parents=True)

        (self.stage / "tools").mkdir(parents=True)
        shutil.copy2(ROOT / "tools" / "production_students_safety.py", self.stage / "tools" / "production_students_safety.py")
        (self.stage / "journal.py").write_text(
            "VALUE = 'stage-journal'\ndef end_date_from_request_payload():\n    return None\ndef public_students_payload(students):\n    return {'students': []}\n",
            encoding="utf-8",
        )
        (self.stage / "pdf_import.py").write_text("VALUE = 'stage-pdf'\n", encoding="utf-8")
        (self.stage / "static" / "app.js").write_text(
            "const copy = 'copy-table-btn';\nconst status = 'lesson-status-btn';\nconst summary = 'practice-summary';\n"
            "function restorePracticeScroll() {}\nconst keepScroll = true;\n"
            "function applyCopiedTable() {}\nfunction applyCopiedRow() {}\nfunction bumpSaveEpoch() {}\n"
            "function syncStartDateWeekday() {}\nconst keepRicher = true;\n"
            "const copyRow = 'row-copy-btn';\nfunction importLinkedPdfs() {}\nfunction ensureEndDateField() {}\nfunction trimRowsToScheduleEnd() {}\nfunction extraLessonRow() {}\nfunction startErrorHtml() {}\n",
            encoding="utf-8",
        )
        (self.stage / "static" / "practice-page.js").write_text(
            "document.body.classList.toggle('practice-open');\n",
            encoding="utf-8",
        )
        (self.stage / "static" / "styles.css").write_text(".stage-styles {}\n", encoding="utf-8")
        (self.stage / "static" / "mobile.css").write_text(".stage-mobile {}\n", encoding="utf-8")
        (self.stage / "static" / "practice-scales.js").write_text("window.practiceScales = null;\n", encoding="utf-8")
        (self.stage / "static" / "practice-scales.css").write_text(".practice-scales { display: none; }\n", encoding="utf-8")

        (self.app / "journal.py").write_text("VALUE = 'old-journal'\n", encoding="utf-8")
        (self.app / "pdf_import.py").write_text("VALUE = 'old-pdf'\n", encoding="utf-8")
        (self.app / "server.py").write_text("PORT = 8765\n", encoding="utf-8")
        (self.app / "static" / "index.html").write_text(
            '<link rel="stylesheet" href="styles.css?v=old" />\n'
            '<link rel="stylesheet" href="mobile.css?v=old" />\n'
            '<link rel="stylesheet" href="practice-scales.css?v=1" />\n'
            '<script src="app.js?v=old"></script>\n'
            '<script src="practice-page.js?v=1"></script>\n'
            '<script src="practice-scales.js?v=1"></script>\n',
            encoding="utf-8",
        )
        (self.app / "static" / "app.js").write_text("old-app\n", encoding="utf-8")
        (self.app / "static" / "styles.css").write_text("old-styles\n", encoding="utf-8")
        (self.app / "static" / "mobile.css").write_text("old-mobile\n", encoding="utf-8")
        (self.app / "data" / "students.json").write_text('{"students":[]}\n', encoding="utf-8")

        self.env = os.environ.copy()
        self.env.update(
            {
                "JOURNAL_STAGE": str(self.stage),
                "JOURNAL_APP_ROOT": str(self.app),
                "JOURNAL_BACKUP_ROOT": str(self.backup),
                "JOURNAL_SKIP_RESTART": "1",
                "JOURNAL_SKIP_HEALTHCHECK": "1",
            }
        )

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_patch_index_only_updates_cache_busters(self) -> None:
        deploy = load_deploy()
        path = self.app / "static" / "index.html"
        deploy.patch_index(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("styles.css?v=students-fix2", text)
        self.assertIn("mobile.css?v=row-copy1", text)
        self.assertIn("app.js?v=students-fix2", text)
        self.assertIn("practice-page.js?v=2", text)
        self.assertIn("practice-scales.css?v=2", text)
        self.assertIn("practice-scales.js?v=2", text)
        self.assertNotIn("?v=old", text)

    def test_patch_server_passes_end_date_without_replacing_file(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            "if start and slots:\n"
            "    journal.apply_schedule(student, start, slots, template)\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("PORT = 8765", text)
        self.assertIn("journal.end_from_payload(locals().get('payload'), start, slots, student.get('schedule'))", text)
        self.assertNotIn("journal.end_from_payload(payload,", text)
        self.assertIn("journal-students-safety-begin", text)
        self.assertIn("production_students_safety", text)
        self.assertNotIn("journal.apply_schedule(student, start, slots, template)\n", text)

    def test_patch_server_rewrites_unsafe_payload_and_students_list(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            "body = json.dumps(payload, ensure_ascii=False).encode(\"utf-8\")\n"
            "if start and slots:\n"
            "    journal.apply_schedule(student, start, slots, template, "
            "journal.end_from_payload(payload, start, slots, student.get('schedule')))\n"
            "self._send_json({\"students\": [public_student(item) for item in data[\"students\"] if public_student(item)]})\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("PORT = 8765", text)
        self.assertIn("locals().get('payload')", text)
        self.assertNotIn("end_from_payload(payload,", text)
        self.assertIn("journal.public_students_payload(data.get('students'))", text)
        self.assertIn('json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")', text)
        self.assertIn("journal-students-safety-begin", text)

    def test_patch_server_always_installs_students_handler(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text("PORT = 8765\n", encoding="utf-8")
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("PORT = 8765", text)
        self.assertIn("journal-students-safety-begin", text)
        self.assertIn("production_students_safety", text)

    def test_installs_files_without_replacing_server_py(self) -> None:
        result = subprocess.run(
            ["python3", str(DEPLOY_PY)],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ГОТОВО. ВСЕ ИЗМЕНЕНИЯ УСТАНОВЛЕНЫ.", result.stdout)
        self.assertIn("VALUE = 'stage-journal'", (self.app / "journal.py").read_text(encoding="utf-8"))
        server_text = (self.app / "server.py").read_text(encoding="utf-8")
        self.assertIn("PORT = 8765", server_text)
        self.assertIn("journal-students-safety-begin", server_text)
        self.assertTrue((self.app / "production_students_safety.py").is_file())
        self.assertIn("restorePracticeScroll", (self.app / "static" / "app.js").read_text(encoding="utf-8"))
        self.assertIn("students-fix2", (self.app / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue((self.app / "static" / "practice-page.js").exists())
        self.assertEqual((self.app / "data" / "students.json").read_text(encoding="utf-8"), '{"students":[]}\n')

    def test_python_script_runs_with_windows_crlf(self) -> None:
        crlf_copy = self.root / "deploy-production.py"
        crlf_copy.write_bytes(DEPLOY_PY.read_bytes().replace(b"\n", b"\r\n"))
        self.assertIn(b"\r\n", crlf_copy.read_bytes())
        result = subprocess.run(
            ["python3", str(crlf_copy)],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ГОТОВО. ВСЕ ИЗМЕНЕНИЯ УСТАНОВЛЕНЫ.", result.stdout)

    def test_gitattributes_forces_lf_for_scripts(self) -> None:
        text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", text)
        self.assertIn("*.py text eol=lf", text)
        self.assertNotIn(b"\r", DEPLOY_PY.read_bytes())
        self.assertNotIn(b"\r", (ROOT / "tools" / "deploy-production.sh").read_bytes())


class ProductionStudentsSafetyTest(unittest.TestCase):
    def test_crashing_handler_still_returns_students_json(self) -> None:
        import importlib.util
        import io
        import json
        import threading

        spec = importlib.util.spec_from_file_location(
            "production_students_safety",
            ROOT / "tools" / "production_students_safety.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class Handler:
            def __init__(self) -> None:
                self.path = "/api/students"
                self.wfile = io.BytesIO()
                self.status = 0

            def do_GET(self) -> None:
                raise RuntimeError("old handler boom")

            def _user(self):
                return {"role": "teacher"}

            def _send_json(self, payload, status=200, cookie=None) -> None:
                raise RuntimeError("should not use old send")

            def send_response(self, status) -> None:
                self.status = status

            def send_header(self, key, value) -> None:
                return None

            def end_headers(self) -> None:
                return None

        journal_mod = type("Journal", (), {})()
        journal_mod.public_students_payload = staticmethod(
            lambda students: {"students": [{"id": "1", "name": "рома", "rows": []}]}
        )
        installed = module.install(
            {
                "Handler": Handler,
                "load_data": lambda: {"students": [{"id": "1", "name": "рома"}]},
                "journal": journal_mod,
                "DATA_LOCK": threading.Lock(),
            }
        )
        self.assertTrue(installed)

        request = Handler()
        Handler.do_GET(request)
        self.assertEqual(request.status, 200)
        body = json.loads(request.wfile.getvalue().decode("utf-8"))
        self.assertEqual(body["students"][0]["name"], "рома")

        other = Handler()
        other.path = "/api/session"
        with self.assertRaises(RuntimeError):
            Handler.do_GET(other)

    def test_safety_block_is_idempotent(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        path = Path(self._temp.name) / "server.py"
        path.write_text("PORT = 8765\n", encoding="utf-8")
        deploy = load_deploy()
        deploy.patch_server(path)
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("journal-students-safety-begin"), 1)
        self._temp.cleanup()


if __name__ == "__main__":
    unittest.main()
