# -*- coding: utf-8 -*-
import json
import tempfile
import time
import unittest
from pathlib import Path

import journal
import server


def filled_row(date_str: str, bank_id: str = "ege-10") -> dict:
    row = journal.empty_row(date_str)
    row.update(
        {
            "topic": "Сложные предложения и знаки препинания",
            "theory": "Конспект: " + ("правило " * 12),
            "homework": "Упражнение 145–148, выписать примеры.",
            "comment": "Разобрать ошибки в задании 10.",
            "bankId": bank_id,
        }
    )
    return row


def filled_student(index: int, lessons: int = 76) -> dict:
    rows = [filled_row(f"{(i % 27) + 1:02d}.09.2026, 16:00") for i in range(lessons)]
    return {
        "id": f"student-{index:03d}",
        "name": f"Ученик {index}",
        "login": f"uchenik{index}",
        "template": "twice",
        "rows": rows,
        "progress": {},
        "schedule": {"startDate": "2025-09-01", "slots": [{"weekday": 0, "time": "16:00"}]},
    }


class PublicStudentTests(unittest.TestCase):
    def tearDown(self):
        journal.invalidate_banks()

    def test_summary_omits_rows(self):
        student = filled_student(1, lessons=40)
        summary = journal.public_student_summary(student)
        self.assertIsNotNone(summary)
        self.assertFalse(summary["tableReady"])
        self.assertNotIn("rows", summary)
        self.assertEqual(summary["name"], "Ученик 1")
        self.assertLess(len(json.dumps(summary, ensure_ascii=False)), 800)

    def test_full_table_marks_ready(self):
        loaded = journal.public_student(filled_student(1, lessons=20))
        self.assertTrue(loaded["tableReady"])
        self.assertEqual(len(loaded["rows"]), 20)
        self.assertTrue(loaded["rows"][0]["practice"])

    def test_stats_computed_once_per_bank(self):
        real = journal.load_bank
        calls = {"n": 0}

        def wrapped(bank_id):
            calls["n"] += 1
            return real(bank_id)

        journal.load_bank = wrapped
        try:
            journal.invalidate_banks()
            journal.public_student(filled_student(1, lessons=80))
            self.assertLessEqual(calls["n"], 3)
        finally:
            journal.load_bank = real

    def test_fifty_summaries_stay_small(self):
        students = [filled_student(i) for i in range(50)]
        summaries = [journal.public_student_summary(item) for item in students]
        blob = json.dumps({"students": summaries}, ensure_ascii=False)
        full = json.dumps({"students": [journal.public_student(item) for item in students]}, ensure_ascii=False)
        self.assertLess(len(blob), 80_000)
        self.assertGreater(len(full) / max(len(blob), 1), 20)


class JournalStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.original = {
            "DATA_DIR": server.DATA_DIR,
            "DATA_FILE": server.DATA_FILE,
            "JOURNAL_DIR": server.JOURNAL_DIR,
            "AUTH_FILE": server.AUTH_FILE,
        }
        server._DATA_CACHE = None
        server.DATA_DIR = root
        server.DATA_FILE = root / "students.json"
        server.JOURNAL_DIR = root / "journal"
        server.AUTH_FILE = root / "auth.json"

    def tearDown(self):
        server._DATA_CACHE = None
        server.DATA_DIR = self.original["DATA_DIR"]
        server.DATA_FILE = self.original["DATA_FILE"]
        server.JOURNAL_DIR = self.original["JOURNAL_DIR"]
        server.AUTH_FILE = self.original["AUTH_FILE"]
        self.tmp.cleanup()

    def test_save_one_student_leaves_other_files(self):
        data = {"students": [filled_student(i, lessons=10) for i in range(5)]}
        server.save_data(data)
        first = server.JOURNAL_DIR / "student-000.json"
        before = first.read_bytes()
        data["students"][1]["rows"][0]["topic"] = "другое"
        time.sleep(0.05)
        server.save_data(data, "student-001")
        self.assertEqual(first.read_bytes(), before)
        second = json.loads((server.JOURNAL_DIR / "student-001.json").read_text(encoding="utf-8"))
        self.assertEqual(second["rows"][0]["topic"], "другое")

    def test_load_roundtrip(self):
        original = {"students": [filled_student(0, lessons=8)]}
        server.save_data(original)
        server._DATA_CACHE = None
        loaded = server.load_data()
        self.assertEqual(loaded["students"][0]["name"], "Ученик 0")
        self.assertEqual(len(loaded["students"][0]["rows"]), 8)

    def test_legacy_students_json_still_loads(self):
        payload = {"students": [filled_student(7, lessons=3)]}
        server.DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        loaded = server.load_data()
        self.assertEqual(loaded["students"][0]["id"], "student-007")
        self.assertEqual(len(loaded["students"][0]["rows"]), 3)


if __name__ == "__main__":
    unittest.main()
