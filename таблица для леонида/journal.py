# -*- coding: utf-8 -*-
"""Даты уроков, банки заданий и прогресс ученика."""

from __future__ import annotations

import copy
import hashlib
import inspect
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
MAX_THEORY_FILES = 12
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
    row["extraLesson"] = False
    for key in FILE_KEYS:
        row[key] = ""
    row["theoryFiles"] = []
    return row


def normalize_theory_files(row: dict | None) -> list[dict]:
    if not isinstance(row, dict):
        return []
    files = []
    seen = set()
    raw = row.get("theoryFiles")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or file_id).strip() or file_id
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            files.append({"id": file_id, "name": name})
    if not files:
        file_id = str(row.get("theoryFileId") or "").strip()
        if file_id:
            files.append({"id": file_id, "name": str(row.get("theoryFileName") or file_id).strip() or file_id})
    return files


def sync_theory_files(row: dict, files: list[dict] | None = None) -> list[dict]:
    items = files if files is not None else normalize_theory_files(row)
    clean = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or file_id).strip() or file_id
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        clean.append({"id": file_id, "name": name})
    row["theoryFiles"] = clean
    if clean:
        row["theoryFileId"] = clean[0]["id"]
        row["theoryFileName"] = clean[0]["name"]
    else:
        row["theoryFileId"] = ""
        row["theoryFileName"] = ""
    return clean


def attach_row_file(row: dict, field: str, stored: str, original: str) -> str:
    """Attach a stored upload. Theory keeps previous files; other fields replace."""
    stored_id = str(stored or "").strip()
    name = str(original or stored_id).strip() or stored_id
    if not isinstance(row, dict) or not stored_id:
        return ""
    if field == "theory":
        files = normalize_theory_files(row)
        if any(item["id"] == stored_id for item in files):
            sync_theory_files(row, files)
            return ""
        if len(files) >= MAX_THEORY_FILES:
            raise ValueError("В теоретический материал можно прикрепить не больше 12 файлов")
        files.append({"id": stored_id, "name": name})
        sync_theory_files(row, files)
        return ""
    old_id = str(row.get(f"{field}FileId") or "")
    row[f"{field}FileId"] = stored_id
    row[f"{field}FileName"] = name
    return old_id


def detach_row_file(row: dict, field: str, file_id: str | None = None) -> str:
    if not isinstance(row, dict):
        return ""
    if field == "theory":
        files = normalize_theory_files(row)
        wanted = str(file_id or "").strip()
        if wanted:
            kept = [item for item in files if item["id"] != wanted]
            removed = wanted if len(kept) != len(files) else ""
        else:
            removed = files[-1]["id"] if files else ""
            kept = files[:-1]
        sync_theory_files(row, kept)
        return removed
    old_id = str(row.get(f"{field}FileId") or "")
    row[f"{field}FileId"] = ""
    row[f"{field}FileName"] = ""
    return old_id


def iter_row_file_ids(row: dict | None):
    if not isinstance(row, dict):
        return
    seen = set()
    for key in FILE_KEYS:
        if not str(key).endswith("FileId"):
            continue
        file_id = str(row.get(key) or "").strip()
        if file_id and file_id not in seen:
            seen.add(file_id)
            yield file_id
    for item in normalize_theory_files(row):
        file_id = item["id"]
        if file_id not in seen:
            seen.add(file_id)
            yield file_id


def last_weekday_in_may(year: int, weekday: int) -> date:
    cursor = date(year, 5, 31)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def school_year_may(start: date) -> int:
    if start.month >= 6:
        return start.year + 1
    return start.year


MAX_SCHEDULE_DAYS = 366 * 4


def default_schedule_end(start: date, slots: list[dict] | None = None) -> date:
    """Last lesson day of the school year in May for the given weekdays."""
    items = [item for item in (slots or []) if isinstance(item, dict)]
    year = school_year_may(start)
    weekdays = []
    for item in items:
        try:
            weekday = int(item.get("weekday"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= weekday <= 6 and weekday not in weekdays:
            weekdays.append(weekday)
    if not weekdays:
        weekdays.append(start.weekday())
    return max(last_weekday_in_may(year, weekday) for weekday in weekdays)


def parse_end_date_value(value) -> tuple[date | None, str]:
    raw = str(value or "").strip()
    if not raw:
        return None, ""
    parsed = parse_iso_date(raw)
    if not parsed:
        return None, "Укажите дату последнего занятия"
    return parsed, ""


def schedule_end_error(start: date, end: date) -> str:
    if end < start:
        return "Дата последнего занятия не может быть раньше первого"
    if (end - start).days > MAX_SCHEDULE_DAYS:
        return "Слишком длинный период: не больше четырёх лет"
    return ""


def resolve_schedule_end(
    start: date,
    slots: list[dict] | None = None,
    requested: date | None = None,
    fallback: date | None = None,
) -> tuple[date, str]:
    if requested is not None:
        end = requested
    elif fallback is not None and fallback >= start:
        end = fallback
    else:
        end = default_schedule_end(start, slots)
    return end, schedule_end_error(start, end)


def end_from_payload(payload, start: date, slots: list[dict] | None = None, existing_schedule=None) -> date:
    requested, _error = parse_end_date_value(payload.get("endDate") if isinstance(payload, dict) else None)
    fallback = None
    if isinstance(existing_schedule, dict):
        fallback = parse_iso_date(str(existing_schedule.get("endDate") or ""))
    if requested is not None:
        return requested
    end, _error = resolve_schedule_end(start, slots, None, fallback)
    return end


def end_date_from_request_payload() -> date | None:
    """Read endDate from the HTTP handler that called apply_schedule.

    Production keeps its own server.py, so the 4-argument apply_schedule call
    never receives the form field. The request payload is still in that frame.
    """
    try:
        frames = inspect.stack(context=0)
    except Exception:
        return None
    here = Path(__file__).resolve()
    try:
        for info in frames:
            try:
                if Path(info.filename).resolve() == here:
                    continue
            except Exception:
                continue
            loc = info.frame.f_locals
            blob = None
            for key in ("payload", "body"):
                value = loc.get(key)
                if isinstance(value, dict) and "endDate" in value:
                    blob = value
                    break
            if blob is None:
                continue
            start = loc.get("start")
            if not isinstance(start, date):
                start = parse_iso_date(str(blob.get("startDate") or loc.get("startDate") or ""))
            if not isinstance(start, date):
                continue
            slots = loc.get("slots")
            if not isinstance(slots, list):
                template = loc.get("template") or blob.get("template") or "once"
                slots = clean_slots(blob.get("slots"), "twice" if template == "twice" else "once")
            student = loc.get("student")
            existing = student.get("schedule") if isinstance(student, dict) else None
            return end_from_payload(blob, start, slots, existing)
    finally:
        del frames
    return None


def is_extra_lesson(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return False
    value = row.get("extraLesson")
    if value is True:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def copy_extra_row(row: dict) -> dict:
    copied = copy.deepcopy(row) if isinstance(row, dict) else empty_row()
    copied["extraLesson"] = True
    return copied


def merge_extra_lessons(scheduled: list[dict], extras: list[dict], old_rows: list[dict]) -> list[dict]:
    result = list(scheduled)
    for extra in extras:
        extra_day = row_day(extra)
        if extra_day is not None:
            insert_at = len(result)
            for index, row in enumerate(result):
                day = row_day(row)
                if day is not None and day > extra_day:
                    insert_at = index
                    break
            result.insert(insert_at, copy_extra_row(extra))
            continue
        old_index = next((index for index, row in enumerate(old_rows) if row is extra), -1)
        prev_scheduled = None
        for index in range(old_index - 1, -1, -1):
            if not is_extra_lesson(old_rows[index]):
                prev_scheduled = old_rows[index]
                break
        if prev_scheduled is None:
            result.insert(0, copy_extra_row(extra))
            continue
        prev_key = row_date_key(prev_scheduled)
        insert_at = 0
        for index, row in enumerate(result):
            if row_date_key(row) == prev_key and not is_extra_lesson(row):
                insert_at = index + 1
                while insert_at < len(result) and is_extra_lesson(result[insert_at]):
                    insert_at += 1
                break
        result.insert(insert_at, copy_extra_row(extra))
    return result


def rows_until_end(rows, end: date | None) -> list:
    if end is None or not isinstance(rows, list):
        return rows if isinstance(rows, list) else []
    kept = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = row_day(row)
        if is_extra_lesson(row) or day is None or day <= end:
            kept.append(row)
    return kept


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


def generate_lesson_dates(start: date, slots: list[dict], end: date | None = None) -> list[str]:
    if not slots:
        return []
    times = {item["weekday"]: item["time"] for item in slots}
    stop = end if end is not None else default_schedule_end(start, slots)
    limit = start + timedelta(days=MAX_SCHEDULE_DAYS)
    if stop > limit:
        stop = limit
    if stop < start:
        return []
    cursor = start
    result = []
    while cursor <= stop:
        if cursor.weekday() in times:
            result.append(f"{cursor.strftime('%d.%m.%Y')}, {times[cursor.weekday()]}")
        cursor += timedelta(days=1)
    return result


def row_date_key(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("date") or "").split(",")[0].strip()


def row_day(row: dict | None) -> date | None:
    return parse_iso_date(row_date_key(row))


def apply_schedule(
    student: dict,
    start: date,
    slots: list[dict],
    template: str,
    end: date | None = None,
) -> None:
    if end is None:
        end = end_date_from_request_payload()
    resolved = end if end is not None else default_schedule_end(start, slots)
    dates = generate_lesson_dates(start, slots, resolved)
    old_rows = [row for row in student.get("rows") or [] if isinstance(row, dict)]
    extras = [row for row in old_rows if is_extra_lesson(row)]
    scheduled_old = [row for row in old_rows if not is_extra_lesson(row)]
    old_by_date = {}
    for row in scheduled_old:
        key = row_date_key(row)
        if key and key not in old_by_date:
            old_by_date[key] = row
    new_rows = []
    for index, date_str in enumerate(dates):
        key = date_str.split(",")[0].strip()
        prev = old_by_date.get(key)
        if prev is None and index < len(scheduled_old):
            prev = scheduled_old[index]
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
        sync_theory_files(row, normalize_theory_files(prev))
        row["extraLesson"] = False
        new_rows.append(row)
    student["rows"] = merge_extra_lessons(new_rows, extras, old_rows)
    student["template"] = template
    student["schedule"] = {
        "startDate": start.isoformat(),
        "endDate": resolved.isoformat(),
        "slots": slots,
    }


def clean_rows(
    rows,
    keep_from_old: list[dict] | None = None,
    student_locked: bool = False,
    end: date | None = None,
) -> list[dict]:
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
        if "theoryFiles" in row or "theoryFileId" in row:
            sync_theory_files(item, normalize_theory_files(row))
        else:
            sync_theory_files(item, normalize_theory_files(prev))
        if student_locked:
            for key in ("topic", "theory", "homework", "comment", "bankId", "importedSource", *FILE_KEYS):
                item[key] = str(prev.get(key, "") or "")
            sync_theory_files(item, normalize_theory_files(prev))
        if item["bankId"]:
            item["practice"] = ""
            item["progress"] = ""
        extra_source = row if "extraLesson" in row else prev
        item["extraLesson"] = is_extra_lesson(extra_source)
        cleaned.append(item)
    return rows_until_end(cleaned, end)


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
    kept_extra = is_extra_lesson(target)
    copied = empty_row(kept_date)
    for key in ROW_COPY_KEYS:
        copied[key] = str(source.get(key) or "")
    status = str(source.get("lessonStatus") or "")
    copied["lessonStatus"] = status if status in LESSON_STATUSES else ""
    copied["extraLesson"] = kept_extra
    sync_theory_files(copied, normalize_theory_files(source))
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
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
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


def purge_bank(data: dict, bank_id: str) -> str:
    safe = re.sub(r"[^a-z0-9\-]", "", str(bank_id or "").lower())
    if not safe.startswith("pdf-"):
        return "Этот набор удалять нельзя"
    delete_bank(safe)
    if not isinstance(data, dict):
        return ""
    for student in data.get("students") or []:
        if not isinstance(student, dict):
            continue
        for row in student.get("rows") or []:
            if isinstance(row, dict) and str(row.get("bankId") or "") == safe:
                row["bankId"] = ""
                row["importedSource"] = "manual:"
        progress = student.get("progress")
        if isinstance(progress, dict):
            progress.pop(safe, None)
            progress.pop(str(bank_id or ""), None)
    return ""


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
    raw_options = task.get("options")
    if not isinstance(raw_options, list):
        raw_options = []
    options = [item for item in raw_options if str(item).strip()]
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


def empty_bank_stats() -> dict:
    return {
        "done": 0,
        "total": 0,
        "correct": 0,
        "percent": 0,
        "donePercent": 0,
        "accuracyPercent": 0,
    }


def bank_stats(student: dict, bank_id: str) -> dict:
    try:
        return _bank_stats(student, bank_id)
    except Exception:
        return empty_bank_stats()


def _bank_stats(student: dict, bank_id: str) -> dict:
    bank = load_bank(bank_id)
    tasks = bank.get("tasks") if isinstance(bank, dict) else None
    if not isinstance(tasks, list):
        tasks = []
    total = len(tasks)
    progress = student.get("progress") if isinstance(student, dict) else None
    answers = progress.get(bank_id) if isinstance(progress, dict) else None
    if not isinstance(answers, dict):
        answers = {}
    done = 0
    correct = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
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


def public_student_stub(student: dict) -> dict:
    schedule = student.get("schedule") if isinstance(student.get("schedule"), dict) else None
    return {
        "id": student.get("id"),
        "name": str(student.get("name") or ""),
        "template": "twice" if student.get("template") == "twice" else "once",
        "login": str(student.get("login") or ""),
        "password_is_initial": bool(student.get("password_is_initial")),
        "rows": [],
        "schedule": schedule,
    }


def public_student(student: dict | None) -> dict | None:
    if not isinstance(student, dict) or not student:
        return None
    try:
        return _public_student(student)
    except Exception:
        return public_student_stub(student)


def _public_student(student: dict) -> dict:
    rows = []
    bank_cache: dict[str, dict | None] = {}
    schedule = student.get("schedule") if isinstance(student.get("schedule"), dict) else None
    end = parse_iso_date(str((schedule or {}).get("endDate") or ""))
    raw_rows = student.get("rows")
    source_rows = rows_until_end(raw_rows if isinstance(raw_rows, list) else [], end)
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        item = {key: str(row.get(key, "") or "") for key in ROW_KEYS}
        status = str(row.get("lessonStatus") or "")
        item["lessonStatus"] = status if status in LESSON_STATUSES else ""
        item["bankId"] = str(row.get("bankId") or "")
        item["importedSource"] = str(row.get("importedSource") or "")
        for key in FILE_KEYS:
            item[key] = str(row.get(key) or "")
        sync_theory_files(item, normalize_theory_files(row))
        if item["bankId"]:
            if item["bankId"] not in bank_cache:
                bank_cache[item["bankId"]] = load_bank(item["bankId"])
            bank = bank_cache[item["bankId"]]
            item["bankTitle"] = str((bank.get("title") if bank else "") or item["bankId"])
            stats = bank_stats(student, item["bankId"])
            item["practice"] = f"{stats['done']}/{stats['total']}"
            item["progress"] = f"{stats['percent']}%"
            item["progressPercent"] = stats["percent"]
            item["progressColor"] = progress_color(stats["percent"])
        item["extraLesson"] = is_extra_lesson(row)
        rows.append(item)
    payload = public_student_stub(student)
    payload["rows"] = rows
    return payload


def public_student_summary(student: dict | None) -> dict | None:
    """List payload used by production server.py GET /api/students."""
    return public_student(student)


def public_students_payload(students) -> dict:
    items = []
    if not isinstance(students, list):
        return {"students": items}
    for item in students:
        try:
            public = public_student(item)
        except Exception:
            continue
        if public:
            items.append(public)
    return {"students": items}


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
