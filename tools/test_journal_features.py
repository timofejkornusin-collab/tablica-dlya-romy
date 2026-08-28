#!/usr/bin/env python3
"""Regression tests for lesson status, table copying, and progress."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import journal
import server


class LessonStatusTest(unittest.TestCase):
    def test_status_is_normalized_and_students_cannot_change_it(self) -> None:
        self.assertEqual(journal.empty_row()["lessonStatus"], "")

        previous = journal.empty_row("01.09.2026, 16:00")
        previous["lessonStatus"] = "held"

        omitted = journal.clean_rows([{"date": previous["date"]}], keep_from_old=[previous])
        self.assertEqual(omitted[0]["lessonStatus"], "held")

        invalid = journal.clean_rows([{"date": previous["date"], "lessonStatus": "unknown"}])
        self.assertEqual(invalid[0]["lessonStatus"], "")

        locked = journal.clean_rows(
            [{"date": previous["date"], "lessonStatus": "missed"}],
            keep_from_old=[previous],
            student_locked=True,
        )
        self.assertEqual(locked[0]["lessonStatus"], "held")

    def test_schedule_regeneration_keeps_status_for_the_same_date(self) -> None:
        row = journal.empty_row("01.09.2026, 16:00")
        row["lessonStatus"] = "missed"
        student = {"rows": [row]}

        journal.apply_schedule(
            student,
            date(2026, 9, 1),
            [{"weekday": 1, "time": "16:00"}],
            "once",
        )

        self.assertEqual(student["rows"][0]["date"], "01.09.2026, 16:00")
        self.assertEqual(student["rows"][0]["lessonStatus"], "missed")
        self.assertEqual(journal.public_student(student)["rows"][0]["lessonStatus"], "missed")


class TableCopyTest(unittest.TestCase):
    def test_copy_replaces_table_but_preserves_identity_and_answers(self) -> None:
        source_row = journal.empty_row("03.09.2026, 18:00")
        source_row.update(
            {
                "lessonStatus": "held",
                "topic": "Орфография",
                "bankId": "ege-10",
                "theoryFileId": "material.pdf",
                "theoryFileName": "Материал.pdf",
            }
        )
        source = {
            "id": "source",
            "name": "Источник",
            "template": "twice",
            "rows": [source_row],
            "schedule": {
                "startDate": "2026-09-03",
                "slots": [{"weekday": 3, "time": "18:00"}, {"weekday": 5, "time": "12:00"}],
            },
            "progress": {"ege-10": {"1": "1"}},
        }
        target_progress = {"ege-10": {"1": "2"}}
        target = {
            "id": "target",
            "name": "Получатель",
            "login": "target-login",
            "template": "once",
            "rows": [journal.empty_row()],
            "schedule": {"startDate": "2025-01-01", "slots": []},
            "progress": target_progress,
        }

        journal.copy_student_table(source, target)

        self.assertEqual(target["id"], "target")
        self.assertEqual(target["name"], "Получатель")
        self.assertEqual(target["login"], "target-login")
        self.assertIs(target["progress"], target_progress)
        self.assertEqual(target["progress"], {"ege-10": {"1": "2"}})
        self.assertEqual(target["template"], "twice")
        self.assertEqual(target["schedule"], source["schedule"])
        self.assertIsNot(target["schedule"], source["schedule"])
        self.assertEqual(target["rows"][0]["topic"], "Орфография")
        self.assertEqual(target["rows"][0]["lessonStatus"], "held")
        self.assertEqual(target["rows"][0]["theoryFileId"], "material.pdf")

        source["rows"][0]["topic"] = "Изменено после копирования"
        self.assertEqual(target["rows"][0]["topic"], "Орфография")

    def test_shared_upload_reference_is_detected(self) -> None:
        first = journal.empty_row()
        first["theoryFileId"] = "shared.pdf"
        second = journal.empty_row()
        second["homeworkFileId"] = "shared.pdf"
        data = {"students": [{"rows": [first]}, {"rows": [second]}]}

        self.assertEqual(server.row_upload_ids([first]), {"shared.pdf"})
        self.assertTrue(server.upload_is_referenced(data, "shared.pdf"))
        self.assertFalse(server.upload_is_referenced(data, "not-an-upload"))


class CorrectProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.banks_dir = Path(self.temp_dir.name)
        bank = {
            "id": "test-bank",
            "title": "Проверка прогресса",
            "tasks": [{"n": number, "prompt": f"Задание {number}", "options": [], "answer": "1"} for number in range(1, 11)],
        }
        (self.banks_dir / "test-bank.json").write_text(
            json.dumps(bank, ensure_ascii=False),
            encoding="utf-8",
        )
        self.patch = patch.object(journal, "BANKS_DIR", self.banks_dir)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_progress_is_correct_answers_out_of_all_tasks(self) -> None:
        answers = {str(number): ("1" if number <= 4 else "2") for number in range(1, 9)}
        row = journal.empty_row()
        row["bankId"] = "test-bank"
        student = {"id": "student", "name": "Ученик", "rows": [row], "progress": {"test-bank": answers}}

        stats = journal.bank_stats(student, "test-bank")
        self.assertEqual(
            stats,
            {
                "done": 8,
                "total": 10,
                "correct": 4,
                "percent": 40,
                "donePercent": 80,
                "accuracyPercent": 50,
            },
        )

        public = journal.public_student(student)
        self.assertEqual(public["rows"][0]["practice"], "8/10")
        self.assertEqual(public["rows"][0]["progress"], "40%")
        self.assertEqual(public["rows"][0]["progressPercent"], 40)
        self.assertEqual(public["rows"][0]["progressColor"], "yellow")


if __name__ == "__main__":
    unittest.main()
