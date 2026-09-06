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

    def test_changing_start_date_updates_journal_dates_and_keeps_topics(self) -> None:
        first = journal.empty_row("03.09.2026, 16:00")
        first["topic"] = "Тема 1"
        second = journal.empty_row("10.09.2026, 16:00")
        second["topic"] = "Тема 2"
        student = {"rows": [first, second]}

        journal.apply_schedule(
            student,
            date(2026, 10, 1),
            [{"weekday": 3, "time": "17:00"}],
            "once",
        )

        self.assertEqual(student["schedule"]["startDate"], "2026-10-01")
        self.assertEqual(student["schedule"]["endDate"], "2027-05-27")
        self.assertEqual(student["rows"][0]["date"], "01.10.2026, 17:00")
        self.assertEqual(student["rows"][0]["topic"], "Тема 1")
        self.assertEqual(student["rows"][1]["date"], "08.10.2026, 17:00")
        self.assertEqual(student["rows"][1]["topic"], "Тема 2")

    def test_same_calendar_date_keeps_its_topic_after_reschedule(self) -> None:
        first = journal.empty_row("03.09.2026, 16:00")
        first["topic"] = "Старт"
        second = journal.empty_row("10.09.2026, 16:00")
        second["topic"] = "Вторая"
        student = {"rows": [first, second]}

        journal.apply_schedule(
            student,
            date(2026, 9, 10),
            [{"weekday": 3, "time": "16:00"}],
            "once",
        )

        self.assertEqual(student["rows"][0]["date"], "10.09.2026, 16:00")
        self.assertEqual(student["rows"][0]["topic"], "Вторая")


class ScheduleEndDateTest(unittest.TestCase):
    def test_default_range_still_stops_in_may(self) -> None:
        slots = [{"weekday": 3, "time": "16:00"}]
        dates = journal.generate_lesson_dates(date(2026, 9, 3), slots)
        self.assertEqual(dates[0], "03.09.2026, 16:00")
        self.assertEqual(dates[-1], "27.05.2027, 16:00")
        self.assertNotIn("03.06.2027, 16:00", dates)
        self.assertEqual(journal.default_schedule_end(date(2026, 9, 3), slots), date(2027, 5, 27))

    def test_june_end_includes_june_lessons(self) -> None:
        slots = [{"weekday": 3, "time": "16:00"}]
        dates = journal.generate_lesson_dates(date(2026, 9, 3), slots, date(2027, 6, 10))
        self.assertIn("27.05.2027, 16:00", dates)
        self.assertIn("03.06.2027, 16:00", dates)
        self.assertIn("10.06.2027, 16:00", dates)
        self.assertNotIn("17.06.2027, 16:00", dates)
        self.assertEqual(dates[-1], "10.06.2027, 16:00")

    def test_two_year_end_keeps_tenth_grade_lessons(self) -> None:
        slots = [{"weekday": 3, "time": "16:00"}]
        dates = journal.generate_lesson_dates(date(2026, 9, 3), slots, date(2028, 5, 25))
        self.assertIn("03.09.2026, 16:00", dates)
        self.assertIn("02.09.2027, 16:00", dates)
        self.assertEqual(dates[-1], "25.05.2028, 16:00")
        years = {item.split(",")[0].split(".")[-1] for item in dates}
        self.assertEqual(years, {"2026", "2027", "2028"})

    def test_end_before_start_is_rejected(self) -> None:
        slots = [{"weekday": 3, "time": "16:00"}]
        self.assertEqual(journal.generate_lesson_dates(date(2026, 9, 3), slots, date(2026, 8, 1)), [])
        end, error = journal.resolve_schedule_end(date(2026, 9, 3), slots, date(2026, 8, 1))
        self.assertEqual(end, date(2026, 8, 1))
        self.assertIn("раньше первого", error)

    def test_apply_schedule_stores_custom_end_date(self) -> None:
        student = {"rows": []}
        journal.apply_schedule(
            student,
            date(2026, 9, 3),
            [{"weekday": 3, "time": "16:00"}],
            "once",
            date(2027, 6, 10),
        )
        self.assertEqual(student["schedule"]["endDate"], "2027-06-10")
        self.assertEqual(student["rows"][-1]["date"], "10.06.2027, 16:00")

    def test_old_server_four_arg_call_honors_payload_end_date(self) -> None:
        payload = {
            "endDate": "2026-12-17",
            "startDate": "2026-09-03",
            "slots": [{"weekday": 3, "time": "16:00"}],
        }
        start = date(2026, 9, 3)
        slots = [{"weekday": 3, "time": "16:00"}]
        template = "once"
        student = {
            "rows": [
                journal.empty_row("03.09.2026, 16:00"),
                journal.empty_row("27.05.2027, 16:00"),
            ]
        }
        journal.apply_schedule(student, start, slots, template)
        self.assertEqual(student["schedule"]["endDate"], "2026-12-17")
        self.assertEqual(student["rows"][-1]["date"], "17.12.2026, 16:00")
        self.assertFalse(any("05.2027" in str(row.get("date")) for row in student["rows"]))
        self.assertFalse(any(str(row.get("date")).startswith("24.12.2026") for row in student["rows"]))

    def test_public_student_hides_rows_after_end_date(self) -> None:
        student = {
            "id": "x",
            "name": "Тест",
            "template": "once",
            "schedule": {"startDate": "2026-09-03", "endDate": "2026-09-10", "slots": []},
            "rows": [
                journal.empty_row("03.09.2026, 16:00"),
                journal.empty_row("10.09.2026, 16:00"),
                journal.empty_row("17.09.2026, 16:00"),
            ],
        }
        public = journal.public_student(student)
        self.assertEqual(
            [row["date"] for row in public["rows"]],
            ["03.09.2026, 16:00", "10.09.2026, 16:00"],
        )

    def test_clean_rows_drops_lessons_after_end(self) -> None:
        rows = [journal.empty_row("03.09.2026, 16:00"), journal.empty_row("17.09.2026, 16:00")]
        cleaned = journal.clean_rows(rows, end=date(2026, 9, 10))
        self.assertEqual([row["date"] for row in cleaned], ["03.09.2026, 16:00"])

    def test_missing_end_date_uses_existing_or_may(self) -> None:
        end, error = journal.resolve_schedule_end(
            date(2026, 9, 3),
            [{"weekday": 3, "time": "16:00"}],
            None,
            date(2027, 6, 15),
        )
        self.assertEqual(error, "")
        self.assertEqual(end, date(2027, 6, 15))

        default_end, default_error = journal.resolve_schedule_end(
            date(2026, 9, 3),
            [{"weekday": 3, "time": "16:00"}],
        )
        self.assertEqual(default_error, "")
        self.assertEqual(default_end, date(2027, 5, 27))

    def test_form_has_last_lesson_date_field(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("ensureEndDateField", app_js)
        self.assertIn("fillEndDateValue", app_js)
        self.assertIn("defaultEndDateForStart", app_js)
        self.assertIn("trimRowsToScheduleEnd", app_js)
        self.assertIn("end_date_from_request_payload", (ROOT / "journal.py").read_text(encoding="utf-8"))
        self.assertIn('id="end-date"', index_html)
        self.assertIn("Дата последнего занятия", index_html)
        self.assertIn("даты встанут до последнего занятия", index_html)
        self.assertNotIn("даты встанут до мая", index_html)


class ExtraLessonTest(unittest.TestCase):
    def test_extra_row_does_not_shift_schedule_dates(self) -> None:
        first = journal.empty_row("03.09.2026, 16:00")
        first["topic"] = "Тема 1"
        extra = journal.empty_row("")
        extra["extraLesson"] = True
        extra["topic"] = "Доп"
        second = journal.empty_row("10.09.2026, 16:00")
        second["topic"] = "Тема 2"
        student = {"rows": [first, extra, second]}

        journal.apply_schedule(
            student,
            date(2026, 9, 3),
            [{"weekday": 3, "time": "16:00"}],
            "once",
        )

        self.assertEqual(student["rows"][0]["date"], "03.09.2026, 16:00")
        self.assertEqual(student["rows"][0]["topic"], "Тема 1")
        self.assertTrue(journal.is_extra_lesson(student["rows"][1]))
        self.assertEqual(student["rows"][1]["topic"], "Доп")
        self.assertEqual(student["rows"][1]["date"], "")
        self.assertEqual(student["rows"][2]["date"], "10.09.2026, 16:00")
        self.assertEqual(student["rows"][2]["topic"], "Тема 2")

    def test_schedule_date_change_keeps_extra_row_and_topics(self) -> None:
        first = journal.empty_row("03.09.2026, 16:00")
        first["topic"] = "Тема 1"
        extra = journal.empty_row("05.09.2026, 18:00")
        extra["extraLesson"] = True
        extra["topic"] = "Суббота"
        second = journal.empty_row("10.09.2026, 16:00")
        second["topic"] = "Тема 2"
        student = {"rows": [first, extra, second]}

        journal.apply_schedule(
            student,
            date(2026, 10, 1),
            [{"weekday": 3, "time": "17:00"}],
            "once",
        )

        extras = [row for row in student["rows"] if journal.is_extra_lesson(row)]
        self.assertEqual(len(extras), 1)
        self.assertEqual(extras[0]["date"], "05.09.2026, 18:00")
        self.assertEqual(extras[0]["topic"], "Суббота")
        thursday = [row for row in student["rows"] if not journal.is_extra_lesson(row)]
        self.assertEqual(thursday[0]["date"], "01.10.2026, 17:00")
        self.assertEqual(thursday[0]["topic"], "Тема 1")
        self.assertEqual(thursday[1]["date"], "08.10.2026, 17:00")
        self.assertEqual(thursday[1]["topic"], "Тема 2")

    def test_extra_row_survives_end_date_trim_and_clean_rows(self) -> None:
        extra = journal.empty_row("20.09.2026, 16:00")
        extra["extraLesson"] = True
        extra["topic"] = "Доп"
        rows = [
            journal.empty_row("03.09.2026, 16:00"),
            extra,
            journal.empty_row("17.09.2026, 16:00"),
        ]
        trimmed = journal.rows_until_end(rows, date(2026, 9, 10))
        self.assertEqual(
            [row["date"] for row in trimmed],
            ["03.09.2026, 16:00", "20.09.2026, 16:00"],
        )
        cleaned = journal.clean_rows(rows)
        self.assertTrue(cleaned[1]["extraLesson"])
        self.assertEqual(journal.public_student({"id": "x", "name": "Т", "rows": cleaned})["rows"][1]["extraLesson"], True)

    def test_app_inserts_extra_row_without_dom_resync(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function extraLessonRow()", app_js)
        self.assertIn("function startErrorHtml(", app_js)
        self.assertIn("skipTableDomSync = true", app_js)
        self.assertIn("student.rows.splice(at, 0, extraLessonRow())", app_js)
        self.assertIn("if (!skipTableDomSync) syncTableRowsFromDom(student)", app_js)
        self.assertIn("дату ставит педагог", app_js)
        self.assertIn("extra-lesson", (ROOT / "static" / "styles.css").read_text(encoding="utf-8"))


class QuietUiTest(unittest.TestCase):
    def test_list_hides_subtitle_login_and_saved_status(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function hideUnwantedLabels()", app_js)
        self.assertIn("function setPageSubtitle(", app_js)
        self.assertIn('setPageSubtitle("")', app_js)
        self.assertNotIn("Между уроками нажмите", app_js)
        self.assertNotIn("Та же таблица, что у педагога", app_js)
        self.assertNotIn("Подготовка к экзаменам и уроки", app_js)
        self.assertNotIn("логин: ${escapeHtml(student.login)}", app_js)
        self.assertIn('value === "Сохранено"', app_js)
        self.assertIn(".card-login {\n  display: none;\n}", styles)
        self.assertIn(".save-status:empty", styles)
        self.assertIn('id="page-subtitle" class="subtitle hidden"', index_html)
        self.assertIn('if (els.shareBar) els.shareBar.classList.add("hidden")', app_js)
        self.assertNotIn('els.shareBar.classList.remove("hidden")', app_js)
        self.assertIn(".share-bar {\n  display: none !important;\n}", styles)


class MaterialPlaceholderTest(unittest.TestCase):
    def test_theory_and_homework_share_file_or_note_placeholder(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('placeholder="файл или заметка"', app_js)
        self.assertNotIn("заметка или ссылка на документ", app_js)
        self.assertNotIn("домашнее задание, ссылка на PDF или файл", app_js)
        self.assertEqual(app_js.count('placeholder="файл или заметка"'), 1)


class StudentTableCellsTest(unittest.TestCase):
    def test_student_date_topic_comment_match_material_cells(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function renderStudentTextCell(", app_js)
        self.assertIn("return renderStudentTextCell(column, row.date || \"\", { extra: badge, linkify: false });", app_js)
        self.assertIn("if (isStudentView()) {\n          return renderStudentTextCell(column, value);\n        }", app_js)
        self.assertNotIn('const readonly = isStudentView() ? "readonly" : "";', app_js)
        self.assertIn(".student-material {\n  padding: 12px;\n  gap: 8px;\n  display: flex;\n  flex-direction: column;\n  color: var(--ink);\n  font-size: 0.93rem;\n}", styles)
        self.assertIn(".teacher-table .lesson-held td.col-date", styles)
        self.assertIn(".teacher-table .lesson-missed td.col-date", styles)
        self.assertNotIn("\n.lesson-held td.col-date {", styles)


class BackToListButtonTest(unittest.TestCase):
    def test_back_button_stays_on_one_line(self) -> None:
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="back-btn"', html)
        self.assertIn("← К списку", html)
        self.assertIn("#back-btn {\n  white-space: nowrap;\n  flex: 0 0 auto;\n}", styles)
        self.assertIn("task21-split1", html)


class TableHeaderLayoutTest(unittest.TestCase):
    def test_table_header_centers_back_and_puts_pill_under_name(self) -> None:
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("body.table-open .topbar {\n  display: grid;", styles)
        self.assertIn("body.table-open .topbar-left {\n  display: contents;\n}", styles)
        self.assertIn("body.table-open #back-btn {\n  align-self: center;\n}", styles)
        self.assertIn("body.table-open .brand-container #page-title {\n  order: 1;\n}", styles)
        self.assertIn("body.table-open .brand-container .brand-pill {\n  order: 2;", styles)
        self.assertIn("body.table-open .brand-container {\n  align-self: start;", styles)


class LogoutOnListOnlyTest(unittest.TestCase):
    def test_teacher_logout_is_only_on_student_cards(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function updateLogoutButton()", app_js)
        self.assertIn('const onStudentCards = isTeacherAccount() && state.view === "list";', app_js)
        self.assertIn("const realStudent = !isTeacherAccount();", app_js)
        self.assertIn("updateLogoutButton();", app_js)
        self.assertNotIn("if (els.logoutBtn) els.logoutBtn.classList.remove(\"hidden\");", app_js)
        self.assertIn("app.js?v=task21-split1", html)


class CardActionsTrimTest(unittest.TestCase):
    def test_cards_keep_open_and_delete_only(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="primary-btn open-table"', app_js)
        self.assertIn('class="danger-btn delete-student"', app_js)
        self.assertNotIn("preview-student", app_js)
        self.assertNotIn("open-settings", app_js)
        self.assertIn('id="preview-btn"', html)
        self.assertIn("Как видит ученик", html)
        self.assertIn('id="settings-btn"', html)
        self.assertIn(">Настройки</button>", html)


class StudentGradeToolbarTest(unittest.TestCase):
    def test_clean_grade_and_public_payload(self) -> None:
        self.assertEqual(journal.clean_grade("  10  "), "10")
        self.assertEqual(journal.clean_grade(None), "")
        self.assertEqual(len(journal.clean_grade("x" * 40)), 24)
        public = journal.public_student_stub({"id": "1", "name": "рома", "grade": "10"})
        self.assertEqual(public["grade"], "10")
        self.assertEqual(journal.public_student({"id": "1", "name": "рома", "grade": "11"})["grade"], "11")

    def test_table_header_has_class_field_and_two_button_rows(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        find_js = (ROOT / "static" / "find-date.js").read_text(encoding="utf-8")
        self.assertIn('id="student-grade"', html)
        self.assertIn("Класс", html)
        self.assertIn('id="brand-tag"', html)
        self.assertIn('id="table-actions-top"', html)
        self.assertIn('id="table-actions-bottom"', html)
        top = html.split('id="table-actions-top"', 1)[1].split('id="table-actions-bottom"', 1)[0]
        bottom = html.split('id="table-actions-bottom"', 1)[1].split("</div>", 1)[0]
        self.assertIn("Как видит ученик", top)
        self.assertIn(">Найти</button>", top)
        self.assertIn("Настройки", top)
        self.assertNotIn("Копировать таблицу", top)
        self.assertIn("Копировать таблицу", bottom)
        self.assertIn("Вставить таблицу", bottom)
        self.assertNotIn("Как видит ученик", bottom)
        self.assertIn("function ensureTableActionLayout()", app_js)
        self.assertIn("function updateBrandPill()", app_js)
        self.assertIn("function gradeTagLabel(", app_js)
        self.assertIn("function ensureGradeField()", app_js)
        self.assertIn('tag.textContent = "10–11 КЛАССЫ"', app_js)
        self.assertIn('document.body.classList.toggle("table-open"', app_js)
        self.assertIn("Укажите класс ученика", app_js)
        self.assertIn("#table-actions {\n  display: flex;\n  flex-direction: column;", styles)
        self.assertNotIn("#table-actions {\n  display: contents;", styles)
        self.assertIn("body.table-open .topbar-left {\n  display: contents;\n}", styles)
        self.assertIn('var top = $("table-actions-top");', find_js)
        self.assertIn("if (top) top.appendChild(btn);", find_js)


class MobileAttachButtonTest(unittest.TestCase):
    def test_phone_and_tablet_show_full_issue_file_button(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        mobile = (ROOT / "static" / "mobile.css").read_text(encoding="utf-8")
        self.assertIn('class="attach-file-label">Выдать файл</span>', app_js)
        self.assertIn("td input:not(.visually-hidden)", styles)
        self.assertIn("td input:not(.visually-hidden)", mobile)
        self.assertIn("td input.visually-hidden", mobile)
        self.assertIn(".file-corner,\n  .practice-upload {\n    position: relative;\n    display: inline-flex;\n    width: 100%;", styles)
        self.assertIn("min-height: 44px", styles)
        self.assertNotIn("width: 36px;\n    height: 36px;\n    background: var(--navy-soft);", styles)
        self.assertIn(".material-cell.student-material {\n    border: 0;", styles)
        self.assertIn(".practice-actions,\n  .bank-picker {", styles)
        self.assertIn(".file-corner .attach-file-label", mobile)
        self.assertIn("overflow: visible !important;", mobile)


class StudentsApiSafetyTest(unittest.TestCase):
    def test_public_student_survives_broken_rows_and_progress(self) -> None:
        student = {
            "id": "broken",
            "name": "Сломанный",
            "rows": "not-a-list",
            "progress": {"ege-10": ["1", "2"]},
            "schedule": {"endDate": "not-a-date", "slots": 3},
        }
        public = journal.public_student(student)
        self.assertEqual(public["id"], "broken")
        self.assertEqual(public["rows"], [])

        mixed = journal.public_students_payload(
            [
                "skip-me",
                None,
                {},
                {
                    "id": "ok",
                    "name": "Ок",
                    "rows": [
                        {
                            "date": "03.09.2026, 16:00",
                            "bankId": "missing-bank",
                            "extraLesson": True,
                            "topic": "Тема",
                        }
                    ],
                    "progress": "nope",
                },
            ]
        )
        self.assertEqual(len(mixed["students"]), 1)
        self.assertEqual(mixed["students"][0]["id"], "ok")
        self.assertTrue(mixed["students"][0]["rows"][0]["extraLesson"])

    def test_bank_stats_ignores_malformed_tasks_and_answers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            banks = Path(folder)
            (banks / "weird.json").write_text(
                json.dumps(
                    {
                        "id": "weird",
                        "title": "Странный",
                        "tasks": ["broken", {"n": 1, "options": 7, "answer": "1"}, {"n": 2, "answer": "2"}],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(journal, "BANKS_DIR", banks):
                stats = journal.bank_stats(
                    {"progress": {"weird": "123"}},
                    "weird",
                )
                self.assertEqual(stats["total"], 3)
                self.assertEqual(stats["done"], 0)
                public = journal.public_student(
                    {
                        "id": "s",
                        "name": "Н",
                        "rows": [{"date": "03.09.2026, 16:00", "bankId": "weird"}],
                        "progress": {"weird": "123"},
                    }
                )
                self.assertEqual(public["rows"][0]["practice"], "0/3")

    def test_public_student_skips_non_dict_entries(self) -> None:
        self.assertIsNone(journal.public_student("рома"))
        self.assertIsNone(journal.public_student(None))
        self.assertIsNone(journal.public_student({}))
        student = {"id": "x", "name": "Т", "rows": [journal.empty_row("03.09.2026, 16:00")]}
        self.assertEqual(journal.public_student_summary(student)["name"], "Т")
        self.assertEqual(journal.public_student_summary(student)["rows"][0]["date"], "03.09.2026, 16:00")


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

    def test_later_save_does_not_drop_pasted_text(self) -> None:
        source_row = journal.empty_row("03.09.2026, 18:00")
        source_row["topic"] = "Орфография"
        source_row["homework"] = "упр. 12"
        source_row["bankId"] = "ege-10"
        source = {
            "rows": [source_row],
            "template": "once",
            "schedule": {"startDate": "2026-09-03", "slots": [{"weekday": 3, "time": "18:00"}]},
        }
        old_target_row = journal.empty_row("01.01.2025, 16:00")
        old_target_row["topic"] = ""
        old_target_row["theoryFileId"] = "old.pdf"
        target = {"id": "ivan", "name": "Иван", "rows": [old_target_row], "template": "once", "progress": {}}

        journal.copy_student_table(source, target)
        edited = [dict(target["rows"][0])]
        edited[0]["comment"] = "правка после вставки"
        saved = journal.clean_rows(edited, keep_from_old=target["rows"])

        self.assertEqual(saved[0]["topic"], "Орфография")
        self.assertEqual(saved[0]["homework"], "упр. 12")
        self.assertEqual(saved[0]["comment"], "правка после вставки")
        self.assertEqual(saved[0]["bankId"], "ege-10")
        self.assertEqual(saved[0]["date"], "03.09.2026, 18:00")

    def test_clean_rows_does_not_reuse_files_from_another_date(self) -> None:
        old = journal.empty_row("01.01.2025, 16:00")
        old["theoryFileId"] = "old.pdf"
        old["topic"] = "старое"
        pasted = journal.empty_row("03.09.2026, 18:00")
        pasted["topic"] = "новое"
        pasted["theoryFileId"] = ""
        saved = journal.clean_rows([pasted], keep_from_old=[old])
        self.assertEqual(saved[0]["topic"], "новое")
        self.assertEqual(saved[0]["theoryFileId"], "")
        self.assertEqual(len(saved), 1)

    def test_shared_upload_reference_is_detected(self) -> None:
        first = journal.empty_row()
        first["theoryFileId"] = "shared.pdf"
        second = journal.empty_row()
        second["homeworkFileId"] = "shared.pdf"
        data = {"students": [{"rows": [first]}, {"rows": [second]}]}

        self.assertEqual(server.row_upload_ids([first]), {"shared.pdf"})
        self.assertTrue(server.upload_is_referenced(data, "shared.pdf"))
        self.assertFalse(server.upload_is_referenced(data, "not-an-upload"))


class RowCopyTest(unittest.TestCase):
    def test_copy_row_keeps_target_date_and_skips_progress(self) -> None:
        source = journal.empty_row("03.09.2026, 18:00")
        source.update(
            {
                "topic": "Орфография",
                "theory": "правила",
                "homework": "упр. 5",
                "comment": "молодец",
                "bankId": "ege-10",
                "lessonStatus": "held",
                "theoryFileId": "t1",
                "theoryFileName": "t.pdf",
                "importedSource": "manual:ege-10",
                "practice": "8/10",
                "progress": "40%",
            }
        )
        target = journal.empty_row("10.09.2026, 17:00")
        target.update({"topic": "старое", "practice": "1/10", "progress": "10%"})

        journal.copy_lesson_row(source, target)

        self.assertEqual(target["date"], "10.09.2026, 17:00")
        self.assertEqual(target["topic"], "Орфография")
        self.assertEqual(target["theory"], "правила")
        self.assertEqual(target["homework"], "упр. 5")
        self.assertEqual(target["comment"], "молодец")
        self.assertEqual(target["bankId"], "ege-10")
        self.assertEqual(target["lessonStatus"], "held")
        self.assertEqual(target["theoryFileId"], "t1")
        self.assertEqual(target["theoryFileName"], "t.pdf")
        self.assertEqual(target["importedSource"], "manual:ege-10")
        self.assertEqual(target["practice"], "")
        self.assertEqual(target["progress"], "")
        source["topic"] = "изменено после копирования"
        self.assertEqual(target["topic"], "Орфография")

    def test_pasted_row_stays_editable_through_clean_rows(self) -> None:
        source = journal.empty_row("03.09.2026, 18:00")
        source["topic"] = "Тема"
        source["bankId"] = "ege-10"
        target = journal.empty_row("17.09.2026, 16:00")
        journal.copy_lesson_row(source, target)
        target["topic"] = "Правка после вставки"
        target["comment"] = "можно менять"
        cleaned = journal.clean_rows([target])
        self.assertEqual(cleaned[0]["date"], "17.09.2026, 16:00")
        self.assertEqual(cleaned[0]["topic"], "Правка после вставки")
        self.assertEqual(cleaned[0]["comment"], "можно менять")
        self.assertEqual(cleaned[0]["bankId"], "ege-10")

    def test_app_has_row_copy_buttons_in_date_cell(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("date-row-tools", app_js)
        self.assertIn("date-cell-bottom", app_js)
        self.assertIn("row-copy-btn", app_js)
        self.assertIn("row-paste-btn", app_js)
        self.assertIn("applyCopiedRow", app_js)
        self.assertIn("journal-row-clipboard-v1", app_js)
        self.assertIn("date-row-tools", styles)
        self.assertIn("const rowTools = `<div class=\"date-row-tools\">", app_js)


class TheoryFilesTest(unittest.TestCase):
    def test_attach_appends_theory_files_and_keeps_old(self) -> None:
        row = journal.empty_row()
        self.assertEqual(journal.attach_row_file(row, "theory", "aaaa.pdf", "Первый.pdf"), "")
        self.assertEqual(journal.attach_row_file(row, "theory", "bbbb.pdf", "Второй.pdf"), "")
        self.assertEqual(row["theoryFileId"], "aaaa.pdf")
        self.assertEqual(row["theoryFileName"], "Первый.pdf")
        self.assertEqual(
            row["theoryFiles"],
            [{"id": "aaaa.pdf", "name": "Первый.pdf"}, {"id": "bbbb.pdf", "name": "Второй.pdf"}],
        )

    def test_detach_one_theory_file_keeps_the_other(self) -> None:
        row = journal.empty_row()
        journal.attach_row_file(row, "theory", "aaaa.pdf", "Первый.pdf")
        journal.attach_row_file(row, "theory", "bbbb.pdf", "Второй.pdf")
        removed = journal.detach_row_file(row, "theory", "aaaa.pdf")
        self.assertEqual(removed, "aaaa.pdf")
        self.assertEqual(row["theoryFileId"], "bbbb.pdf")
        self.assertEqual(row["theoryFiles"], [{"id": "bbbb.pdf", "name": "Второй.pdf"}])

    def test_homework_still_replaces_single_file(self) -> None:
        row = journal.empty_row()
        self.assertEqual(journal.attach_row_file(row, "homework", "old.doc", "old.doc"), "")
        self.assertEqual(journal.attach_row_file(row, "homework", "new.doc", "new.doc"), "old.doc")
        self.assertEqual(row["homeworkFileId"], "new.doc")

    def test_theory_file_limit(self) -> None:
        row = journal.empty_row()
        for index in range(journal.MAX_THEORY_FILES):
            journal.attach_row_file(row, "theory", f"{index:02d}.pdf", f"{index}.pdf")
        with self.assertRaises(ValueError):
            journal.attach_row_file(row, "theory", "zz.pdf", "too-many.pdf")

    def test_public_student_includes_theory_files(self) -> None:
        student = {"id": "s", "name": "Н", "rows": [journal.empty_row()]}
        journal.attach_row_file(student["rows"][0], "theory", "aaaa.pdf", "A.pdf")
        journal.attach_row_file(student["rows"][0], "theory", "bbbb.pdf", "B.pdf")
        public = journal.public_student(student)
        self.assertEqual(len(public["rows"][0]["theoryFiles"]), 2)

    def test_copy_row_copies_all_theory_files(self) -> None:
        source = journal.empty_row("03.09.2026, 18:00")
        journal.attach_row_file(source, "theory", "aaaa.pdf", "A.pdf")
        journal.attach_row_file(source, "theory", "bbbb.pdf", "B.pdf")
        target = journal.empty_row("10.09.2026, 17:00")
        journal.copy_lesson_row(source, target)
        self.assertEqual(len(target["theoryFiles"]), 2)
        self.assertEqual(target["date"], "10.09.2026, 17:00")

    def test_upload_ids_include_extra_theory_files(self) -> None:
        row = journal.empty_row()
        journal.attach_row_file(row, "theory", "aaaa.pdf", "A.pdf")
        journal.attach_row_file(row, "theory", "bbbb.pdf", "B.pdf")
        self.assertEqual(server.row_upload_ids([row]), {"aaaa.pdf", "bbbb.pdf"})

    def test_app_renders_multiple_theory_files(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("rowTheoryFiles", app_js)
        self.assertIn("file-chip", app_js)
        self.assertIn('field === "theory" ? "multiple"', app_js)
        self.assertIn("data-file-id", app_js)
        self.assertIn("fileId: remove.dataset.fileId", app_js)
        self.assertIn(".file-chip", styles)
        self.assertIn("attach_row_file", (ROOT / "journal.py").read_text(encoding="utf-8"))
        self.assertIn("journal.attach_row_file", (ROOT / "server.py").read_text(encoding="utf-8"))
        self.assertIn("min-height: 148px", styles)
        self.assertNotIn("max-height: 46%", styles)
        self.assertIn("td {\n  padding: 0;\n  background: #ffffff;\n  height: auto;", styles)
        self.assertIn("content: none !important", styles)
        self.assertIn(".file-chip .file-remove::after", styles)
        self.assertIn("max-height: none !important", (ROOT / "static" / "mobile.css").read_text(encoding="utf-8"))


class BankKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.banks_dir = Path(self.temp_dir.name)
        self.patch = patch.object(journal, "BANKS_DIR", self.banks_dir)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp_dir.cleanup()

    def _save(self, task: dict, raw: str) -> dict:
        bank = {"id": "keys-bank", "title": "Ключи", "tasks": [task]}
        journal.save_bank(bank)
        self.assertTrue(journal.set_bank_key("keys-bank", int(task["n"]), raw))
        return journal.load_bank("keys-bank")["tasks"][0]

    def test_word_and_long_number_keys_are_kept(self) -> None:
        word_task = {
            "n": 1,
            "prompt": "Исправьте ошибку и запишите слово правильно.",
            "options": [],
            "kind": "word",
            "answer": "",
        }
        saved = self._save(word_task, "ДВУХСТА")
        self.assertEqual(saved["answer"], "ДВУХСТА")

        choice = {
            "n": 2,
            "prompt": "Запишите номера ответов.",
            "options": ["а", "б", "в", "г", "д"],
            "answer": "",
        }
        saved = self._save(choice, "2, 4, 5")
        self.assertEqual(saved["answer"], "245")
        self.assertEqual(journal.normalize_answer("452"), "245")

        sequence = {
            "n": 3,
            "prompt": "Установите соответствие. Запишите цифры.",
            "options": [],
            "answer": "",
        }
        saved = self._save(sequence, "5724613")
        self.assertEqual(saved["answer"], "5724613")

        passage = {
            "n": 4,
            "prompt": "Укажите номера предложений.",
            "options": [],
            "answer": "",
        }
        saved = self._save(passage, "2, 15, 18")
        self.assertEqual(saved["answer"], "21518")
        self.assertEqual(journal.normalize_answer("15, 2, 18"), "21518")

    def test_letters_are_not_stripped_from_a_choice_task(self) -> None:
        task = {
            "n": 1,
            "prompt": "Запишите номера ответов.",
            "options": ["а", "б", "в", "г", "д"],
            "answer": "",
        }
        saved = self._save(task, "ПРИВЕТ")
        self.assertEqual(saved["answer"], "ПРИВЕТ")
        self.assertEqual(journal.normalize_answer("привет", word=False), "привет")

    def test_app_does_not_import_theory_or_homework_pdfs_into_practice(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        server_py = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("importLinkedPdfs", app_js)
        self.assertIn("firstPdfUrl(row.practice)", app_js)
        self.assertNotIn("firstPdfUrl(row.theory)", app_js)
        self.assertNotIn("firstPdfUrl(row.homework)", app_js)
        self.assertNotIn('fromField: "theory"', app_js)
        self.assertNotIn('fromField: "homework"', app_js)
        self.assertIn('fromField: "practice"', app_js)
        self.assertIn('from_field == "practice"', server_py)
        self.assertNotIn('from_field in ("homework", "practice", "theory")', server_py)
        self.assertIn('field == "practice" and suffix == ".pdf"', server_py)
        self.assertNotIn('field in ("practice", "theory", "homework") and suffix == ".pdf"', server_py)
        upload_fn = server_py.split("def _upload_material", 1)[1].split("def _delete_material", 1)[0]
        self.assertNotIn("pdf_import.import_pdf_bytes", upload_fn)
        self.assertIn("needsImport", upload_fn)
        self.assertIn("MAX_PDF_PAGES", (ROOT / "pdf_import.py").read_text(encoding="utf-8"))

    def test_app_can_delete_imported_practice_banks(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("deletePracticeBank", app_js)
        self.assertIn("bank-delete", app_js)
        self.assertIn("bank-picker-toggle", app_js)
        self.assertIn("bank-picker-choice", app_js)
        self.assertIn("bank-picker-name", app_js)
        self.assertIn("practice-open-hint", app_js)
        self.assertIn("practice-upload", app_js)
        self.assertIn("bank-picker-layer", app_js)
        self.assertIn("bank-picker-list", app_js)
        self.assertNotIn("showPopover", app_js)
        self.assertNotIn('popover="manual"', app_js)
        self.assertIn('class="practice-upload"', app_js)
        self.assertNotIn('class="file-corner" title="Загрузить PDF с заданиями"', app_js)
        self.assertNotIn("bank-files-toggle", app_js)
        self.assertIn("/api/banks/delete", app_js)
        self.assertNotIn('window.addEventListener("scroll", closeBankPickers, true)', app_js)
        self.assertNotIn('addEventListener(\n  "pointerdown"', app_js)
        self.assertNotIn('"pointerdown"', app_js)
        self.assertIn('row.importedSource = row.bankId ? `manual:${row.bankId}` : "manual:"', app_js)
        delete_fn = app_js.split("async function deletePracticeBank", 1)[1].split("function rowHasLessonContent", 1)[0]
        self.assertLess(delete_fn.index("confirm("), delete_fn.index("closeBankPickers()"))
        self.assertIn("purge_bank", (ROOT / "journal.py").read_text(encoding="utf-8"))
        self.assertIn(".bank-delete", styles)
        self.assertIn("background: #ffffff", styles)
        self.assertIn(".bank-picker-layer", styles)
        self.assertIn("overflow: hidden", styles)
        self.assertIn("text-overflow: ellipsis", styles)
        self.assertIn("flex-shrink: 0", styles)
        self.assertIn("class=\"file-pick\"", app_js)
        self.assertIn("Date.now() < bankMenuIgnoreUntil", app_js)
        self.assertIn("persistCurrent({ quiet: true })", app_js)
        self.assertIn("/api/import-pdf", app_js)
        self.assertIn("needsImport", app_js)
        self.assertIn("Сервер не ответил", app_js)


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


class PurgeBankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.banks_dir = Path(self.temp_dir.name)
        (self.banks_dir / "ege-10.json").write_text(
            json.dumps({"id": "ege-10", "title": "Задание 10 ЕГЭ", "tasks": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.banks_dir / "pdf-abc123def456.json").write_text(
            json.dumps({"id": "pdf-abc123def456", "title": "Лишний PDF", "tasks": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.patch = patch.object(journal, "BANKS_DIR", self.banks_dir)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_purge_bank_removes_pdf_set_and_clears_student_links(self) -> None:
        data = {
            "students": [
                {
                    "id": "roma",
                    "rows": [{"bankId": "pdf-abc123def456", "importedSource": "file:theory.pdf"}],
                    "progress": {"pdf-abc123def456": {"1": "ответ"}, "ege-10": {"1": "1"}},
                }
            ]
        }
        err = journal.purge_bank(data, "pdf-abc123def456")
        self.assertEqual(err, "")
        self.assertFalse((self.banks_dir / "pdf-abc123def456.json").exists())
        self.assertTrue((self.banks_dir / "ege-10.json").exists())
        row = data["students"][0]["rows"][0]
        self.assertEqual(row["bankId"], "")
        self.assertEqual(row["importedSource"], "manual:")
        self.assertNotIn("pdf-abc123def456", data["students"][0]["progress"])
        self.assertEqual(data["students"][0]["progress"]["ege-10"], {"1": "1"})

    def test_purge_bank_keeps_builtin_ege_set(self) -> None:
        data = {"students": [{"rows": [{"bankId": "ege-10"}]}]}
        err = journal.purge_bank(data, "ege-10")
        self.assertEqual(err, "Этот набор удалять нельзя")
        self.assertTrue((self.banks_dir / "ege-10.json").exists())
        self.assertEqual(data["students"][0]["rows"][0]["bankId"], "ege-10")

    def test_purge_bank_clears_stale_pdf_id_even_if_file_is_gone(self) -> None:
        data = {"students": [{"rows": [{"bankId": "pdf-missing0001", "importedSource": "manual:pdf-missing0001"}]}]}
        err = journal.purge_bank(data, "pdf-missing0001")
        self.assertEqual(err, "")
        self.assertEqual(data["students"][0]["rows"][0]["bankId"], "")
        self.assertEqual(data["students"][0]["rows"][0]["importedSource"], "manual:")


if __name__ == "__main__":
    unittest.main()
