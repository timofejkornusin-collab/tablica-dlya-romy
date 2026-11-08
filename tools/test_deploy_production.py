#!/usr/bin/env python3
"""Tests for the CRLF-safe production deploy helper."""

from __future__ import annotations

import importlib.util
import json
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
            "VALUE = 'stage-journal'\ndef end_date_from_request_payload():\n    return None\ndef public_students_payload(students):\n    return {'students': []}\ndef public_student_summary(student):\n    return student\ndef purge_bank(data, bank_id):\n    return ''\ndef attach_row_file(row, field, stored, original):\n    return ''\ndef clean_grade(raw):\n    return str(raw or '')[:24]\nMAX_THEORY_FILES = 12\n",
            encoding="utf-8",
        )
        (self.stage / "pdf_import.py").write_text("VALUE = 'stage-pdf'\n", encoding="utf-8")
        (self.stage / "static" / "app.js").write_text(
            "const copy = 'copy-table-btn';\nconst status = 'lesson-status-btn';\nconst summary = 'practice-summary';\n"
            "function restorePracticeScroll() {}\nconst keepScroll = true;\n"
            "function applyCopiedTable() {}\nfunction applyCopiedRow() {}\nfunction bumpSaveEpoch() {}\n"
            "function syncStartDateWeekday() {}\nconst keepRicher = true;\n"
            "const copyRow = 'row-copy-btn';\nfunction importLinkedPdfs() {}\nfunction ensureEndDateField() {}\nfunction trimRowsToScheduleEnd() {}\nfunction extraLessonRow() {}\nfunction startErrorHtml() {}\nfunction hideUnwantedLabels() {}\nfunction setPageSubtitle() {}\nfunction deletePracticeBank() {}\nconst bankDelete = 'bank-delete';\nconst bankToggle = 'bank-picker-toggle';\nconst bankChoice = 'bank-picker-choice';\nconst bankName = 'bank-picker-name';\nconst openHint = 'practice-open-hint';\nconst practiceUpload = 'practice-upload';\nconst layer = 'bank-picker-layer';\nconst list = 'bank-picker-list';\nconst theoryFiles = 'theoryFiles';\nfunction rowTheoryFiles() {}\nfunction renderStudentTextCell() {}\nconst attachLabel = 'attach-file-label';\nfunction updateLogoutButton() {}\nfunction ensureTableActionLayout() {}\nfunction updateBrandPill() {}\nfunction ensureGradeField() {}\nconst pick = 'file-pick';\nconst needsImport = 'needsImport';\nconst serverDown = 'Сервер не ответил';\nfunction formatStoredPrompt() {}\nconst flow = 'task-prompt-flow';\nconst passage = 'task.passage';\nfunction studentShareUrl() {}\nfunction shouldShowLogin() {}\nfunction isPublicJournalHost() {}\n",
            encoding="utf-8",
        )
        (self.stage / "static" / "practice-page.js").write_text(
            "document.body.classList.toggle('practice-open');\n",
            encoding="utf-8",
        )
        (self.stage / "static" / "find-date.js").write_text(
            "var top = 'table-actions-top';\n",
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
            '<script src="find-date.js?v=old"></script>\n'
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
        self.assertIn("styles.css?v=load2", text)
        self.assertIn("mobile.css?v=load2", text)
        self.assertIn("app.js?v=load2", text)
        self.assertIn("find-date.js?v=class-bar1", text)
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

    def test_patch_server_stops_theory_and_homework_pdf_import(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            'if field in ("practice", "theory", "homework") and suffix == ".pdf":\n'
            "    parsed_bank = True\n"
            'if field == "practice" or not str(rows[row_index].get("bankId") or ""):\n'
            '    rows[row_index]["bankId"] = parsed_bank["id"]\n'
            'elif from_field in ("homework", "practice", "theory"):\n'
            "    pass\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn('field == "practice" and suffix == ".pdf"', text)
        self.assertNotIn('field in ("practice", "theory", "homework")', text)
        self.assertIn('from_field == "practice"', text)
        self.assertNotIn('from_field in ("homework", "practice", "theory")', text)
        self.assertIn('if field == "practice":', text)
        self.assertNotIn('or not str(rows[row_index].get("bankId")', text)

    def test_patch_server_skips_pdf_parse_during_upload(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            'if field == "practice" and suffix == ".pdf":\n'
            "            try:\n"
            "                parsed_bank = pdf_import.import_pdf_bytes(\n"
            '                    uploaded["data"], original, journal.pdf_bank_id(uploaded["data"])\n'
            "                )\n"
            "            except Exception:\n"
            "                parsed_bank = None\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("if False:", text)
        self.assertNotIn(
            'if field == "practice" and suffix == ".pdf":\n            try:\n                parsed_bank = pdf_import.import_pdf_bytes(',
            text,
        )

    def test_patch_server_appends_theory_files(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            "class H:\n"
            "    def m(self, rows, row_index, field, stored, original, payload):\n"
            "            old_id = safe_upload_id(str(rows[row_index].get(f\"{field}FileId\") or \"\"))\n"
            "            rows[row_index][f\"{field}FileId\"] = stored\n"
            "            rows[row_index][f\"{field}FileName\"] = original\n"
            "            old_id = safe_upload_id(str(rows[row_index].get(f\"{field}FileId\") or \"\"))\n"
            "            rows[row_index][f\"{field}FileId\"] = \"\"\n"
            "            rows[row_index][f\"{field}FileName\"] = \"\"\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("journal.attach_row_file", text)
        self.assertIn("journal.detach_row_file", text)
        self.assertNotIn('[f"{field}FileId"] = stored', text)
        self.assertNotIn('[f"{field}FileName"] = ""', text)

    def test_patch_server_replaces_pinggy_public_url(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "PORT = 8765\n"
            'payload = {"publicUrl": PUBLIC_URL, "ok": True}\n',
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn('"publicUrl": "https://rusklasst.ru"', text)
        self.assertNotIn('"publicUrl": PUBLIC_URL', text)

    def test_patch_server_disables_loopback_teacher(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "class H:\n"
            "    def _user(self):\n"
            "        if is_loopback(self.client_address[0]):\n"
            '            return {\n'
            '                "role": "teacher",\n'
            '                "local": True,\n'
            "            }\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("if False:", text)
        self.assertNotIn("if is_loopback(self.client_address[0]):", text)

    def test_patch_server_extends_session_cookie(self) -> None:
        deploy = load_deploy()
        path = self.app / "server.py"
        path.write_text(
            "class H:\n"
            "    def _cookie_header(self, token: str | None, max_age: int = 60 * 60 * 14) -> str:\n"
            "        return 'x'\n",
            encoding="utf-8",
        )
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("max_age: int = 60 * 60 * 24 * 30", text)
        self.assertNotIn("max_age: int = 60 * 60 * 14", text)

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
        self.assertIn("load2", (self.app / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("load2", (self.app / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue((self.app / "static" / "practice-page.js").exists())
        self.assertTrue((self.app / "static" / "find-date.js").exists())
        self.assertEqual((self.app / "data" / "students.json").read_text(encoding="utf-8"), '{"students":[]}\n')

    def test_install_seed_banks_writes_three_banks(self) -> None:
        deploy = load_deploy()
        deploy.STAGE = self.stage
        deploy.APP_ROOT = self.app
        seed = self.stage / "seed-banks"
        seed.mkdir()
        for name in ("pdf-ege1.json", "pdf-ege2.json", "pdf-ege3.json"):
            shutil.copy2(ROOT / "seed-banks" / name, seed / name)
        deploy.install_seed_banks()
        for bank_id, title in (("pdf-ege1", "Задание 1"), ("pdf-ege2", "Задание 2"), ("pdf-ege3", "Задание 3")):
            path = self.app / "data" / "banks" / f"{bank_id}.json"
            self.assertTrue(path.is_file(), bank_id)
            bank = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(bank["id"], bank_id)
            self.assertEqual(bank["title"], title)
            self.assertGreaterEqual(len(bank["tasks"]), 90)

    def test_repo_seed_banks_are_ready_to_copy(self) -> None:
        deploy = load_deploy()
        for filename, bank_id, title in deploy.SEED_BANKS:
            path = ROOT / "seed-banks" / filename
            self.assertTrue(path.is_file(), filename)
            bank = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(bank["id"], bank_id)
            self.assertEqual(bank["title"], title)
            self.assertGreaterEqual(len(bank["tasks"]), 90)

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

    def test_teacher_can_delete_pdf_bank_via_safety_post(self) -> None:
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
                self.path = "/api/banks/delete"
                self.wfile = io.BytesIO()
                self.status = 0

            def do_GET(self) -> None:
                raise RuntimeError("old get boom")

            def do_POST(self) -> None:
                raise RuntimeError("old post boom")

            def _user(self):
                return {"role": "teacher"}

            def _read_json(self):
                return {"id": "pdf-abc123def456"}

            def send_response(self, status) -> None:
                self.status = status

            def send_header(self, key, value) -> None:
                return None

            def end_headers(self) -> None:
                return None

        saved = {}
        journal_mod = type("Journal", (), {})()
        journal_mod.purge_bank = staticmethod(
            lambda data, bank_id: data.setdefault("purged", []).append(bank_id) or ""
        )
        journal_mod.list_banks = staticmethod(lambda: [{"id": "ege-10"}])
        journal_mod.public_students_payload = staticmethod(
            lambda students: {"students": students or []}
        )
        data_store = {"students": [{"id": "1", "name": "рома"}]}
        installed = module.install(
            {
                "Handler": Handler,
                "load_data": lambda: data_store,
                "save_data": lambda data: saved.update(data),
                "journal": journal_mod,
                "DATA_LOCK": threading.Lock(),
            }
        )
        self.assertTrue(installed)

        request = Handler()
        Handler.do_POST(request)
        self.assertEqual(request.status, 200)
        body = json.loads(request.wfile.getvalue().decode("utf-8"))
        self.assertTrue(body["ok"])
        self.assertEqual(body["banks"][0]["id"], "ege-10")
        self.assertEqual(saved["purged"], ["pdf-abc123def456"])

        other = Handler()
        other.path = "/api/login"
        Handler.do_POST(other)
        self.assertEqual(other.status, 500)
        login_body = json.loads(other.wfile.getvalue().decode("utf-8"))
        self.assertFalse(login_body.get("ok", True))
        self.assertTrue(login_body.get("error"))

    def test_safety_create_table_delete_work_when_old_post_crashes(self) -> None:
        import importlib.util
        import io
        import json
        import sys
        import threading

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import journal

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
                self.payload = {}
                self.wfile = io.BytesIO()
                self.status = 0
                self._headers_sent = False

            def do_GET(self) -> None:
                raise RuntimeError("old get boom")

            def do_POST(self) -> None:
                raise RuntimeError("old post boom")

            def _user(self):
                return {"role": "teacher", "student_id": None}

            def _read_json(self):
                return self.payload

            def send_response(self, status) -> None:
                self.status = status

            def send_header(self, key, value) -> None:
                return None

            def end_headers(self) -> None:
                self._headers_sent = True

        data_store = {"students": []}
        installed = module.install(
            {
                "Handler": Handler,
                "load_data": lambda: data_store,
                "save_data": lambda data: data_store.update({"students": list(data.get("students") or [])}),
                "journal": journal,
                "DATA_LOCK": threading.Lock(),
                "hash_password": lambda password: ("salt", "digest"),
                "generate_password": lambda: "pass-word",
                "slug_login": lambda name: "roma",
            }
        )
        self.assertTrue(installed)

        create = Handler()
        create.payload = {
            "name": "рома",
            "grade": "10",
            "template": "once",
            "startDate": "2026-09-03",
            "slots": [{"weekday": 3, "time": "16:00"}],
        }
        Handler.do_POST(create)
        self.assertEqual(create.status, 200)
        created = json.loads(create.wfile.getvalue().decode("utf-8"))
        self.assertTrue(created["ok"])
        self.assertEqual(created["student"]["name"], "рома")
        self.assertEqual(created["student"]["grade"], "10")
        self.assertGreater(len(created["student"]["rows"]), 0)
        student_id = created["student"]["id"]
        self.assertEqual(data_store["students"][0]["grade"], "10")

        table = Handler()
        table.path = "/api/table"
        table.payload = {
            "id": student_id,
            "template": "once",
            "rows": [
                {
                    "date": created["student"]["rows"][0]["date"],
                    "topic": "Тема",
                    "bankId": "",
                    "importedSource": "manual:",
                }
            ],
        }
        Handler.do_POST(table)
        self.assertEqual(table.status, 200)
        saved = json.loads(table.wfile.getvalue().decode("utf-8"))
        self.assertEqual(saved["student"]["rows"][0]["topic"], "Тема")

        schedule = Handler()
        schedule.path = "/api/schedule"
        schedule.payload = {
            "id": student_id,
            "name": "рома",
            "grade": "11",
            "template": "once",
            "startDate": "2026-09-03",
            "slots": [{"weekday": 3, "time": "16:00"}],
        }
        Handler.do_POST(schedule)
        self.assertEqual(schedule.status, 200)
        self.assertEqual(data_store["students"][0]["grade"], "11")

        paste = Handler()
        paste.path = "/api/schedule"
        paste.payload = {
            "id": student_id,
            "name": "рома",
            "template": "once",
            "startDate": "2026-09-03",
            "slots": [{"weekday": 3, "time": "16:00"}],
        }
        Handler.do_POST(paste)
        self.assertEqual(paste.status, 200)
        self.assertEqual(data_store["students"][0]["grade"], "11")

        delete = Handler()
        delete.path = "/api/students/delete"
        delete.payload = {"id": student_id}
        Handler.do_POST(delete)
        self.assertEqual(delete.status, 200)
        self.assertEqual(data_store["students"], [])

        other = Handler()
        other.path = "/api/login"
        Handler.do_POST(other)
        self.assertEqual(other.status, 500)
        login_body = json.loads(other.wfile.getvalue().decode("utf-8"))
        self.assertFalse(login_body.get("ok", True))
        self.assertTrue(login_body.get("error"))

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

    def test_safety_installs_before_main_guard(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        path = Path(self._temp.name) / "server.py"
        path.write_text(
            "PORT = 8765\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
            encoding="utf-8",
        )
        deploy = load_deploy()
        deploy.patch_server(path)
        text = path.read_text(encoding="utf-8")
        self.assertLess(text.index("journal-students-safety-begin"), text.index("if __name__ == '__main__':"))
        self._temp.cleanup()


if __name__ == "__main__":
    unittest.main()
