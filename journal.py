# -*- coding: utf-8 -*-
"""Даты уроков, банки заданий и прогресс ученика."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BANKS_DIR = DATA_DIR / "banks"
ROW_KEYS = ("date", "topic", "theory", "practice", "progress", "homework", "comment")
FILE_KEYS = (
    "theoryFileId",
    "theoryFileName",
    "homeworkFileId",
    "homeworkFileName",
    "practiceFileId",
    "practiceFileName",
)
LESSON_STATUSES = {"held", "missed"}
ROW_COPY_KEYS = (
    "topic",
    "theory",
    "homework",
    "comment",
    "bankId",
    "importedSource",
    *FILE_KEYS,
)
WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def empty_row(date_str: str = "") -> dict:
    row = {key: "" for key in ROW_KEYS}
    row["date"] = date_str
    row["lessonStatus"] = ""
    row["bankId"] = ""
    row["importedSource"] = ""
    for key in FILE_KEYS:
        row[key] = ""
    return row


def last_weekday_in_may(year: int, weekday: int) -> date:
    cursor = date(year, 5, 31)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def school_year_may(start: date) -> int:
    if start.month >= 6:
        return start.year + 1
    return start.year


def parse_iso_date(value: str) -> date | None:
    raw = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def normalize_time(value: str) -> str:
    raw = str(value or "16:00").strip()
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError:
        return "16:00"
    return parsed.strftime("%H:%M")


def clean_slots(raw_slots, template: str) -> list[dict]:
    slots = []
    if not isinstance(raw_slots, list):
        return slots
    seen = set()
    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        try:
            weekday = int(item.get("weekday"))
        except (TypeError, ValueError):
            continue
        if weekday < 0 or weekday > 6 or weekday in seen:
            continue
        seen.add(weekday)
        slots.append({"weekday": weekday, "time": normalize_time(str(item.get("time") or "16:00"))})
        if template != "twice" and len(slots) == 1:
            break
        if template == "twice" and len(slots) == 2:
            break
    return slots


def generate_lesson_dates(start: date, slots: list[dict]) -> list[str]:
    if not slots:
        return []
    times = {item["weekday"]: item["time"] for item in slots}
    year = school_year_may(start)
    end = max(last_weekday_in_may(year, item["weekday"]) for item in slots)
    cursor = start
    result = []
    while cursor <= end:
        if cursor.weekday() in times:
            result.append(f"{cursor.strftime('%d.%m.%Y')}, {times[cursor.weekday()]}")
        cursor += timedelta(days=1)
    return result


def row_date_key(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("date") or "").split(",")[0].strip()


def apply_schedule(student: dict, start: date, slots: list[dict], template: str) -> None:
    dates = generate_lesson_dates(start, slots)
    old_rows = [row for row in student.get("rows") or [] if isinstance(row, dict)]
    old_by_date = {}
    for row in old_rows:
        key = row_date_key(row)
        if key and key not in old_by_date:
            old_by_date[key] = row
    new_rows = []
    for index, date_str in enumerate(dates):
        key = date_str.split(",")[0].strip()
        prev = old_by_date.get(key)
        if prev is None and index < len(old_rows):
            prev = old_rows[index]
        if prev is None:
            prev = {}
        row = empty_row(date_str)
        for field in (
            "topic",
            "theory",
            "homework",
            "comment",
            "lessonStatus",
            "bankId",
            "importedSource",
            *FILE_KEYS,
        ):
            row[field] = str(prev.get(field) or "")
        if row["lessonStatus"] not in LESSON_STATUSES:
            row["lessonStatus"] = ""
        new_rows.append(row)
    student["rows"] = new_rows
    student["template"] = template
    student["schedule"] = {
        "startDate": start.isoformat(),
        "slots": slots,
    }


def clean_rows(rows, keep_from_old: list[dict] | None = None, student_locked: bool = False) -> list[dict]:
    cleaned = []
    old = keep_from_old or []
    if not isinstance(rows, list):
        return cleaned
    old_by_date = {}
    for prev_row in old:
        key = row_date_key(prev_row)
        if key and key not in old_by_date:
            old_by_date[key] = prev_row
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        date_key = row_date_key(row)
        prev = old_by_date.get(date_key) if date_key else None
        if prev is None and index < len(old) and isinstance(old[index], dict):
            prev = old[index]
        if prev is None:
            prev = {}
        item = empty_row()
        for key in ROW_KEYS:
            item[key] = str(row.get(key, "") or "")
        if "bankId" in row:
            item["bankId"] = str(row.get("bankId") or "")
        else:
            item["bankId"] = str(prev.get("bankId") or "")
        if "importedSource" in row:
            item["importedSource"] = str(row.get("importedSource") or "")
        else:
            item["importedSource"] = str(prev.get("importedSource") or "")
        raw_status = row.get("lessonStatus") if "lessonStatus" in row else prev.get("lessonStatus")
        if student_locked:
            raw_status = prev.get("lessonStatus")
        item["lessonStatus"] = str(raw_status or "") if str(raw_status or "") in LESSON_STATUSES else ""
        for key in FILE_KEYS:
            if key in row:
                item[key] = str(row.get(key) or "")
            else:
                item[key] = str(prev.get(key) or "")
        if student_locked:
            for key in ("topic", "theory", "homework", "comment", "bankId", "importedSource", *FILE_KEYS):
                item[key] = str(prev.get(key, "") or "")
        if item["bankId"]:
            item["practice"] = ""
            item["progress"] = ""
        cleaned.append(item)
    return cleaned


def copy_student_table(source: dict, target: dict) -> None:
    """Replace a target's lesson table without copying identity or answers."""
    source_rows = source.get("rows") if isinstance(source.get("rows"), list) else []
    target["rows"] = clean_rows(copy.deepcopy(source_rows))
    target["template"] = "twice" if source.get("template") == "twice" else "once"
    schedule = source.get("schedule")
    if isinstance(schedule, dict):
        target["schedule"] = copy.deepcopy(schedule)
    else:
        target.pop("schedule", None)


def copy_lesson_row(source: dict | None, target: dict | None) -> dict:
    """Copy one lesson's teaching content into another row, keeping the target date.

    Progress and student answers stay with the student, not the row.
    """
    if not isinstance(target, dict):
        target = empty_row()
    if not isinstance(source, dict):
        source = empty_row()
    kept_date = str(target.get("date") or "")
    copied = empty_row(kept_date)
    for key in ROW_COPY_KEYS:
        copied[key] = str(source.get(key) or "")
    status = str(source.get("lessonStatus") or "")
    copied["lessonStatus"] = status if status in LESSON_STATUSES else ""
    target.clear()
    target.update(copied)
    return target


def load_bank(bank_id: str) -> dict | None:
    safe = re.sub(r"[^a-z0-9\-]", "", str(bank_id or "").lower())
    path = BANKS_DIR / f"{safe}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        return None
    raw["id"] = safe
    return raw


def save_bank(bank: dict) -> None:
    BANKS_DIR.mkdir(parents=True, exist_ok=True)
    path = BANKS_DIR / f"{bank['id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_banks() -> list[dict]:
    BANKS_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for path in sorted(BANKS_DIR.glob("*.json")):
        bank = load_bank(path.stem)
        if not bank:
            continue
        result.append(
            {
                "id": bank["id"],
                "title": bank.get("title") or bank["id"],
                "total": len(bank.get("tasks") or []),
            }
        )
    result.sort(key=lambda item: (0 if item["id"] == "ege-10" else 1, item["title"].casefold(), item["id"]))
    return result


def pdf_bank_id(pdf_bytes: bytes) -> str:
    return "pdf-" + hashlib.sha256(pdf_bytes).hexdigest()[:12]


def delete_bank(bank_id: str) -> None:
    safe = re.sub(r"[^a-z0-9\-]", "", str(bank_id or "").lower())
    if not safe.startswith("pdf-"):
        return
    path = BANKS_DIR / f"{safe}.json"
    path.unlink(missing_ok=True)


def bank_used(data: dict, bank_id: str) -> bool:
    wanted = str(bank_id or "")
    if not wanted:
        return False
    for student in data.get("students") or []:
        if not isinstance(student, dict):
            continue
        for row in student.get("rows") or []:
            if isinstance(row, dict) and str(row.get("bankId") or "") == wanted:
                return True
    return False


def is_word_task(task: dict | None) -> bool:
    if not isinstance(task, dict):
        return False
    kind = str(task.get("kind") or "")
    if kind in {"phrases", "word"}:
        return True
    if kind in {"match", "choice"}:
        return False
    options = [item for item in (task.get("options") or []) if str(item).strip()]
    if len(options) >= 3:
        return False
    prompt = str(task.get("prompt") or "").lower()
    if any(hint in prompt for hint in ("запишите номера", "номера ответов", "номера этих", "цифру", "цифры", "цифр")):
        return False
    return any(
        hint in prompt
        for hint in (
            "запишите слово",
            "запишите это слово",
            "слово правильно",
            "выпишите",
            "грамматическая ошибка",
            "исправьте ошибку",
            "лексическ",
            "отредактируйте",
            "постановке ударения",
        )
    )


def looks_like_word_answer(raw: str) -> bool:
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", str(raw or "")))


def normalize_answer(raw: str, word: bool = False) -> str:
    text = str(raw or "").strip()
    if word or looks_like_word_answer(text):
        return re.sub(r"\s+", "", text).casefold()
    if re.search(r"[,\s;]+", text):
        nums = [int(part) for part in re.findall(r"\d+", text)]
        return "".join(str(n) for n in sorted(set(nums))) if nums else ""
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if "0" not in digits and max(digits) <= "5" and len(digits) <= 5:
        return "".join(sorted(set(digits)))
    return digits


def bank_stats(student: dict, bank_id: str) -> dict:
    bank = load_bank(bank_id)
    total = len(bank.get("tasks") or []) if bank else 0
    answers = ((student.get("progress") or {}).get(bank_id) or {}) if isinstance(student.get("progress"), dict) else {}
    done = 0
    correct = 0
    if bank:
        for task in bank["tasks"]:
            word = is_word_task(task)
            given = normalize_answer(str(answers.get(str(task.get("n")), "") or ""), word=word)
            if not given:
                continue
            done += 1
            key = normalize_answer(str(task.get("answer") or ""), word=word)
            if key and given == key:
                correct += 1
    done_percent = int(round(100 * done / total)) if total else 0
    percent = int(round(100 * correct / total)) if total else 0
    accuracy_percent = int(round(100 * correct / done)) if done else 0
    return {
        "done": done,
        "total": total,
        "correct": correct,
        "percent": percent,
        "donePercent": done_percent,
        "accuracyPercent": accuracy_percent,
    }


def progress_color(percent: int) -> str:
    if percent < 20:
        return "red"
    if percent < 50:
        return "yellow"
    if percent < 80:
        return "light"
    return "dark"


def public_student(student: dict | None) -> dict | None:
    if not student:
        return None
    rows = []
    bank_cache: dict[str, dict | None] = {}
    for row in student.get("rows") or []:
        if not isinstance(row, dict):
            continue
        item = {key: str(row.get(key, "") or "") for key in ROW_KEYS}
        status = str(row.get("lessonStatus") or "")
        item["lessonStatus"] = status if status in LESSON_STATUSES else ""
        item["bankId"] = str(row.get("bankId") or "")
        item["importedSource"] = str(row.get("importedSource") or "")
        for key in FILE_KEYS:
            item[key] = str(row.get(key) or "")
        if item["bankId"]:
            if item["bankId"] not in bank_cache:
                bank_cache[item["bankId"]] = load_bank(item["bankId"])
            bank = bank_cache[item["bankId"]]
            item["bankTitle"] = (bank.get("title") if bank else "") or item["bankId"]
            stats = bank_stats(student, item["bankId"])
            item["practice"] = f"{stats['done']}/{stats['total']}"
            item["progress"] = f"{stats['percent']}%"
            item["progressPercent"] = stats["percent"]
            item["progressColor"] = progress_color(stats["percent"])
        rows.append(item)
    return {
        "id": student.get("id"),
        "name": student.get("name") or "",
        "template": "twice" if student.get("template") == "twice" else "once",
        "login": student.get("login") or "",
        "password_is_initial": bool(student.get("password_is_initial")),
        "rows": rows,
        "schedule": student.get("schedule") if isinstance(student.get("schedule"), dict) else None,
    }


def public_practice(bank: dict, student: dict, role: str) -> dict:
    answers = ((student.get("progress") or {}).get(bank["id"]) or {}) if isinstance(student.get("progress"), dict) else {}
    tasks = []
    for task in bank.get("tasks") or []:
        number = task.get("n")
        given = str(answers.get(str(number), "") or "")
        word = is_word_task(task)
        key = normalize_answer(str(task.get("answer") or ""), word=word)
        item = {
            "n": number,
            "prompt": task.get("prompt") or bank.get("instruction") or "",
            "options": task.get("options") or [],
            "kind": str(task.get("kind") or ""),
            "word": word,
            "given": given,
            "status": "empty",
        }
        if role == "teacher":
            item["answer"] = str(task.get("answer") or "")
        if given and key:
            if normalize_answer(given, word=word) == key:
                item["status"] = "ok"
            else:
                item["status"] = "bad"
                item["correctAnswer"] = str(task.get("answer") or "")
        elif given:
            item["status"] = "saved"
        item["locked"] = bool(given) and role != "teacher"
        tasks.append(item)
    stats = bank_stats(student, bank["id"])
    return {
        "id": bank["id"],
        "title": bank.get("title") or bank["id"],
        "instruction": bank.get("instruction") or "",
        "tasks": tasks,
        "stats": stats,
        "statsColor": progress_color(stats["percent"]),
    }


def has_task_answer(student: dict, bank_id: str, number: int) -> bool:
    answers = ((student.get("progress") or {}).get(bank_id) or {}) if isinstance(student.get("progress"), dict) else {}
    if not isinstance(answers, dict):
        return False
    return bool(str(answers.get(str(number), "") or "").strip())


def set_task_answer(student: dict, bank_id: str, number: int, answer: str) -> dict:
    progress = student.setdefault("progress", {})
    if not isinstance(progress, dict):
        progress = {}
        student["progress"] = progress
    bucket = progress.setdefault(bank_id, {})
    if not isinstance(bucket, dict):
        bucket = {}
        progress[bank_id] = bucket
    normalized_input = str(answer or "").strip()
    if not normalized_input:
        bucket.pop(str(number), None)
    else:
        bucket[str(number)] = normalized_input
    return bank_stats(student, bank_id)


def set_bank_key(bank_id: str, number: int, answer: str) -> bool:
    bank = load_bank(bank_id)
    if not bank:
        return False
    found = False
    for task in bank["tasks"]:
        if int(task.get("n") or 0) == number:
            raw = str(answer or "").strip()
            if not raw:
                task["answer"] = ""
            elif is_word_task(task) or looks_like_word_answer(raw):
                task["answer"] = raw
            else:
                stored = normalize_answer(raw, word=False)
                task["answer"] = stored or raw
            found = True
            break
    if found:
        save_bank(bank)
    return found
