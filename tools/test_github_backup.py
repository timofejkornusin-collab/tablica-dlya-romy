#!/usr/bin/env python3
"""Резервная копия забирает учеников и файлы, но не сессии входа."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_backup():
    spec = importlib.util.spec_from_file_location("github_backup", ROOT / "tools" / "github-backup.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GithubBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backup = load_backup()

    def test_sessions_are_left_out(self) -> None:
        root = Path(self.id().replace(".", "-"))
        journal = Path(os.environ.get("TMPDIR", "/tmp")) / root
        self.addCleanup(lambda: __import__("shutil").rmtree(journal, ignore_errors=True))
        data = journal / "data"
        (data / "banks").mkdir(parents=True)
        (data / "uploads").mkdir()
        (data / "students.json").write_text('{"students":[{"name":"Аня"}]}\n', encoding="utf-8")
        (data / "auth.json").write_text("{}\n", encoding="utf-8")
        (data / "sessions.json").write_text('{"token":"secret"}\n', encoding="utf-8")
        (data / "known_hosts").write_text("secret\n", encoding="utf-8")
        (data / "banks" / "task.json").write_text("{}\n", encoding="utf-8")
        (data / "uploads" / "sheet.pdf").write_bytes(b"%PDF")
        (data / "students.json.tmp").write_text("partial\n", encoding="utf-8")
        tools = journal / "tools"
        tools.mkdir()
        (tools / "github-backup.py").write_text("print('old')\n", encoding="utf-8")
        (tools / "deploy-production.py").write_text("print('deploy')\n", encoding="utf-8")
        relative = {item[1] for item in self.backup.iter_backup_files(journal)}
        self.assertIn("data/students.json", relative)
        self.assertIn("data/auth.json", relative)
        self.assertIn("data/banks/task.json", relative)
        self.assertIn("data/uploads/sheet.pdf", relative)
        self.assertNotIn("data/sessions.json", relative)
        self.assertNotIn("data/known_hosts", relative)
        self.assertNotIn("data/students.json.tmp", relative)
        self.assertNotIn("tools/github-backup.py", relative)
        self.assertIn("tools/deploy-production.py", relative)

    def test_commit_records_a_student_change(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = root / "journal"
            repo = root / "repo"
            (journal / "data").mkdir(parents=True)
            (journal / "data" / "students.json").write_text(
                json.dumps({"students": [{"name": "Аня"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (journal / "data" / "sessions.json").write_text('{"secret":true}\n', encoding="utf-8")
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            (repo / "README").write_text("backup\n", encoding="utf-8")
            subprocess.run(["git", "add", "README"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "start"], cwd=repo, check=True, capture_output=True)
            self.assertTrue(self.backup.backup_once(journal, repo, "main", push=False))
            saved = json.loads((repo / "data" / "students.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["students"][0]["name"], "Аня")
            self.assertFalse((repo / "data" / "sessions.json").exists())
            self.assertFalse(self.backup.backup_once(journal, repo, "main", push=False))
            (journal / "data" / "students.json").write_text(
                json.dumps({"students": [{"name": "Боря"}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertTrue(self.backup.backup_once(journal, repo, "main", push=False))
            saved = json.loads((repo / "data" / "students.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["students"][0]["name"], "Боря")


if __name__ == "__main__":
    unittest.main()
