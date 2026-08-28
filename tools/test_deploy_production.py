#!/usr/bin/env python3
"""Tests for the CRLF-safe production deploy helper."""

from __future__ import annotations

import importlib.util
import os
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

        (self.stage / "journal.py").write_text("VALUE = 'stage-journal'\n", encoding="utf-8")
        (self.stage / "pdf_import.py").write_text("VALUE = 'stage-pdf'\n", encoding="utf-8")
        (self.stage / "static" / "app.js").write_text(
            "const copy = 'copy-table-btn';\nconst status = 'lesson-status-btn';\nconst summary = 'practice-summary';\n",
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
        self.assertIn("styles.css?v=table-tools3", text)
        self.assertIn("mobile.css?v=table-tools3", text)
        self.assertIn("app.js?v=table-tools3", text)
        self.assertIn("practice-scales.css?v=2", text)
        self.assertIn("practice-scales.js?v=2", text)
        self.assertNotIn("?v=old", text)

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
        self.assertEqual((self.app / "journal.py").read_text(encoding="utf-8"), "VALUE = 'stage-journal'\n")
        self.assertEqual((self.app / "server.py").read_text(encoding="utf-8"), "PORT = 8765\n")
        self.assertIn("copy-table-btn", (self.app / "static" / "app.js").read_text(encoding="utf-8"))
        self.assertIn("table-tools3", (self.app / "static" / "index.html").read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    unittest.main()
