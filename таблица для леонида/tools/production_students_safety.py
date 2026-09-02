# -*- coding: utf-8 -*-
"""Safe GET/POST wrappers for production server.py that we do not replace.

Production keeps its own server.py. After a successful save it often closes the
socket without a JSON body (nginx then shows 502, the site says «Ошибка запроса»).
This module answers those routes itself and always writes JSON.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
import secrets
import traceback
import uuid
from pathlib import Path
from urllib.parse import unquote


ERROR_LOG = Path("/tmp/journal-students-error.log")
_grade_job = contextvars.ContextVar("journal_grade_job", default=None)
UPLOAD_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".odt",
    ".txt",
    ".rtf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _write_error(exc: BaseException | None = None) -> None:
    try:
        text = traceback.format_exc() if exc is None else "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        ERROR_LOG.write_text(text, encoding="utf-8")
    except Exception:
        return


def _headers_sent(handler) -> bool:
    return bool(getattr(handler, "_headers_sent", False))


def _send_json(handler, payload, status: int = 200) -> None:
    if _headers_sent(handler):
        return
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")
    except Exception as exc:
        _write_error(exc)
        body = json.dumps({"ok": False, "error": "Не получилось отдать данные"}, ensure_ascii=False).encode("utf-8")
        status = 500
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(body)
        try:
            handler.wfile.flush()
        except Exception:
            pass
    except Exception as exc:
        _write_error(exc)


def _find_handler(g: dict):
    handler = g.get("Handler")
    if isinstance(handler, type) and hasattr(handler, "do_GET"):
        return handler
    for value in list(g.values()):
        try:
            if isinstance(value, type) and hasattr(value, "do_GET") and hasattr(value, "_send_json"):
                return value
        except Exception:
            continue
    return None


def _load_data(g: dict) -> dict:
    loader = g.get("load_data")
    if callable(loader):
        data = loader()
        return data if isinstance(data, dict) else {"students": []}
    return {"students": []}


def _find_student(g: dict, data: dict, student_id: str):
    finder = g.get("find_student")
    if callable(finder):
        return finder(data, student_id)
    wanted = str(student_id or "")
    for item in data.get("students") or []:
        if isinstance(item, dict) and item.get("id") == wanted:
            return item
    return None


def _students_payload(g: dict, data: dict) -> dict:
    journal = g.get("journal")
    students = data.get("students") if isinstance(data, dict) else []
    if journal is not None and hasattr(journal, "public_students_payload"):
        return journal.public_students_payload(students)
    if journal is not None and hasattr(journal, "public_student"):
        items = []
        for item in students or []:
            try:
                public = journal.public_student(item)
            except Exception:
                continue
            if public:
                items.append(public)
        return {"students": items}
    return {"students": []}


def _public_one(g: dict, student):
    journal = g.get("journal")
    if journal is not None and hasattr(journal, "public_student"):
        try:
            return journal.public_student(student)
        except Exception as exc:
            _write_error(exc)
            return None
    return None


def _hold_lock(g: dict):
    lock = g.get("DATA_LOCK")
    acquired = False
    try:
        if lock is not None and hasattr(lock, "acquire"):
            try:
                acquired = bool(lock.acquire(True, 8))
            except TypeError:
                lock.acquire()
                acquired = True
        return acquired, lock
    except Exception:
        return False, lock


def _release_lock(acquired: bool, lock) -> None:
    if acquired and lock is not None:
        try:
            lock.release()
        except Exception:
            pass


def _locked_data(g: dict) -> dict:
    acquired, lock = _hold_lock(g)
    try:
        return _load_data(g)
    finally:
        _release_lock(acquired, lock)


def _save_data(g: dict, data: dict) -> None:
    saver = g.get("save_data")
    if callable(saver):
        saver(data)


def _request_json(handler):
    reader = getattr(handler, "_read_json", None)
    if callable(reader):
        return reader()
    length = 0
    try:
        length = int((getattr(handler, "headers", {}) or {}).get("Content-Length", "0") or "0")
    except (TypeError, ValueError, AttributeError):
        length = 0
    raw = b""
    rfile = getattr(handler, "rfile", None)
    if length > 0 and rfile is not None:
        raw = rfile.read(length)
    try:
        data = json.loads((raw or b"{}").decode("utf-8") or "{}")
    except Exception:
        _send_json(handler, {"ok": False, "error": "Некорректный JSON"}, 400)
        return None
    return data if isinstance(data, dict) else {}


def _require_user(handler):
    user = handler._user() if hasattr(handler, "_user") else None
    if not user:
        _send_json(handler, {"ok": False, "error": "Нужно войти"}, 401)
        return None
    return user


def _require_teacher(handler):
    user = _require_user(handler)
    if user is None:
        return None
    if user.get("role") != "teacher":
        _send_json(handler, {"ok": False, "error": "Это действие доступно учителю"}, 403)
        return None
    return user


def _clean_grade(g: dict, raw) -> str:
    journal = g.get("journal")
    cleaner = getattr(journal, "clean_grade", None) if journal is not None else None
    if callable(cleaner):
        try:
            return str(cleaner(raw) or "")
        except Exception:
            pass
    return " ".join(str(raw or "").split())[:24]


def _hash_password(g: dict, password: str):
    fn = g.get("hash_password")
    if callable(fn):
        return fn(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return salt, digest


def _generate_password(g: dict) -> str:
    fn = g.get("generate_password")
    if callable(fn):
        return str(fn() or "")
    alphabet = "abcdefghijkmnopqrstuvwxyz23456789"
    chars = [secrets.choice(alphabet) for _ in range(8)]
    return "".join(chars[:4]) + "-" + "".join(chars[4:])


def _slug_login(g: dict, name: str) -> str:
    fn = g.get("slug_login")
    if callable(fn):
        try:
            return str(fn(name) or "uchenik")
        except Exception:
            pass
    text = re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())
    return text[:18] or "uchenik"


def _login_taken(g: dict, data: dict, login: str, skip_id: str | None = None) -> bool:
    folded = str(login or "").casefold()
    if not folded:
        return True
    auth_loader = g.get("load_auth")
    if callable(auth_loader):
        try:
            auth = auth_loader() or {}
            if str(auth.get("teacher_login") or "").casefold() == folded:
                return True
        except Exception:
            pass
    for item in data.get("students") or []:
        if not isinstance(item, dict):
            continue
        if skip_id and item.get("id") == skip_id:
            continue
        if str(item.get("login") or "").casefold() == folded:
            return True
    return False


def _empty_rows(g: dict) -> list:
    journal = g.get("journal")
    if journal is not None and hasattr(journal, "empty_row"):
        return [journal.empty_row() for _ in range(5)]
    return [{"date": "", "topic": "", "theory": "", "practice": "", "progress": "", "homework": "", "comment": ""} for _ in range(5)]


def _uploads_dir(g: dict) -> Path:
    raw = g.get("UPLOADS_DIR")
    return raw if isinstance(raw, Path) else Path(str(raw or "/var/www/journal/data/uploads"))


def _safe_upload_id(g: dict, raw: str) -> str:
    fn = g.get("safe_upload_id")
    if callable(fn):
        try:
            return str(fn(raw) or "")
        except Exception:
            pass
    name = Path(str(raw or "")).name
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,80}", name):
        return ""
    if Path(name).suffix.lower() not in UPLOAD_EXTENSIONS:
        return ""
    return name


def _parse_multipart(g: dict, handler):
    fn = g.get("parse_multipart")
    length = int((getattr(handler, "headers", {}) or {}).get("Content-Length", "0") or "0")
    if length <= 0 or length > MAX_UPLOAD_BYTES:
        return None
    raw = handler.rfile.read(length) if getattr(handler, "rfile", None) is not None else b""
    if callable(fn):
        return fn(handler.headers, raw)
    content_type = (getattr(handler, "headers", {}) or {}).get("Content-Type", "")
    match = re.search(r"boundary=([^;]+)", content_type, re.I)
    if not match:
        return {"fields": {}, "file": None}
    boundary = match.group(1).strip().strip('"').encode("utf-8")
    fields: dict[str, str] = {}
    uploaded = None
    for raw_part in raw.split(b"--" + boundary):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--" or part.startswith(b"--"):
            continue
        header_blob, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        header_text = header_blob.decode("utf-8", "replace")
        name_match = re.search(r'name="([^"]+)"', header_text)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', header_text)
        if filename_match is not None:
            uploaded = {
                "filename": unquote(filename_match.group(1)),
                "data": data.rstrip(b"\r\n"),
            }
        else:
            fields[name] = data.rstrip(b"\r\n").decode("utf-8", "replace")
    return {"fields": fields, "file": uploaded}


def _student_for_grade(g: dict, data: dict, path: str, payload: dict):
    if path.rstrip("/").endswith("schedule"):
        return _find_student(g, data, str(payload.get("id") or ""))
    name = str(payload.get("name") or "").strip()
    if not name:
        return None
    for item in reversed(list(data.get("students") or [])):
        if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
            return item
    return None


def _apply_grade_to_data(g: dict, data: dict, path: str, payload) -> bool:
    if not isinstance(data, dict) or not isinstance(payload, dict):
        return False
    grade = _clean_grade(g, payload.get("grade"))
    if not grade:
        return False
    student = _student_for_grade(g, data, path, payload)
    if not isinstance(student, dict):
        return False
    if str(student.get("grade") or "") == grade:
        return False
    student["grade"] = grade
    return True


def _wrap_read_json(handler_cls) -> None:
    orig_read_json = getattr(handler_cls, "_read_json", None)
    if not callable(orig_read_json) or getattr(orig_read_json, "_journal_json_cached", False):
        return

    def _read_json(self):
        if getattr(self, "_journal_json_read", False):
            return getattr(self, "_journal_json_cache", None)
        self._journal_json_read = True
        data = orig_read_json(self)
        self._journal_json_cache = data
        job = _grade_job.get()
        if job is not None and isinstance(data, dict):
            job["payload"] = data
        return data

    _read_json._journal_json_cached = True
    handler_cls._read_json = _read_json


def _wrap_save_data(g: dict) -> None:
    orig_save = g.get("save_data")
    if not callable(orig_save) or getattr(orig_save, "_journal_grade_wrapped", False):
        return

    def save_data(data):
        job = _grade_job.get()
        if job and isinstance(job.get("payload"), dict):
            _apply_grade_to_data(g, data, str(job.get("path") or ""), job["payload"])
        orig_save(data)

    save_data._journal_grade_wrapped = True
    g["save_data"] = save_data


def _wrap_handler_send_json(handler_cls) -> None:
    orig = getattr(handler_cls, "_send_json", None)
    if not callable(orig) or getattr(orig, "_journal_send_safe", False):
        return

    def _safe_send_json(self, payload, status: int = 200, cookie: str | None = None) -> None:
        if _headers_sent(self):
            return
        try:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")
        except Exception as exc:
            _write_error(exc)
            body = json.dumps({"ok": False, "error": "Не получилось отдать данные"}, ensure_ascii=False).encode("utf-8")
            status = 500
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)
            try:
                self.wfile.flush()
            except Exception:
                pass
        except Exception as exc:
            _write_error(exc)

    _safe_send_json._journal_send_safe = True
    handler_cls._send_json = _safe_send_json


def _post_create_student(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        _send_json(handler, {"ok": False, "error": "Нужно имя ученика"}, 400)
        return
    grade = _clean_grade(g, payload.get("grade"))
    if not grade:
        _send_json(handler, {"ok": False, "error": "Укажите класс ученика"}, 400)
        return
    journal = g.get("journal")
    template = "twice" if payload.get("template") == "twice" else "once"
    login = str(payload.get("login") or "").strip() or _slug_login(g, name)
    login = login.replace(" ", "")
    password = str(payload.get("password") or "").strip() or _generate_password(g)
    start = None
    slots = []
    end = None
    if journal is not None:
        start = journal.parse_iso_date(str(payload.get("startDate") or "")) if hasattr(journal, "parse_iso_date") else None
        slots = journal.clean_slots(payload.get("slots"), template) if hasattr(journal, "clean_slots") else []
        if hasattr(journal, "parse_end_date_value"):
            requested_end, end_error = journal.parse_end_date_value(payload.get("endDate"))
            if end_error:
                _send_json(handler, {"ok": False, "error": end_error}, 400)
                return
        else:
            requested_end = None
        if start and slots and hasattr(journal, "resolve_schedule_end"):
            end, span_error = journal.resolve_schedule_end(start, slots, requested_end)
            if span_error:
                _send_json(handler, {"ok": False, "error": span_error}, 400)
                return
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        if not isinstance(data.get("students"), list):
            data["students"] = []
        base = login
        suffix = 2
        while _login_taken(g, data, login):
            login = f"{base}{suffix}"
            suffix += 1
        salt, digest = _hash_password(g, password)
        student = {
            "id": str(uuid.uuid4()),
            "name": name,
            "grade": grade,
            "login": login,
            "template": template,
            "rows": _empty_rows(g),
            "progress": {},
            "password_salt": salt,
            "password_hash": digest,
            "password_is_initial": False,
        }
        if journal is not None and start and slots and hasattr(journal, "apply_schedule"):
            journal.apply_schedule(student, start, slots, template, end)
        data["students"].append(student)
        _save_data(g, data)
        saved = _public_one(g, student)
    finally:
        _release_lock(acquired, lock)
    _send_json(
        handler,
        {
            "ok": True,
            "student": saved,
            "login": login,
            "password": password,
        },
    )


def _post_delete_student(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    student_id = str((payload or {}).get("id") or "")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        data["students"] = [item for item in (data.get("students") or []) if not (isinstance(item, dict) and item.get("id") == student_id)]
        _save_data(g, data)
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True})


def _post_student_password(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    student_id = str((payload or {}).get("id") or "")
    password = str((payload or {}).get("password") or "").strip()
    if payload.get("reset") or not password:
        password = _generate_password(g)
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        salt, digest = _hash_password(g, password)
        student["password_salt"] = salt
        student["password_hash"] = digest
        student["password_is_initial"] = False
        _save_data(g, data)
        login = str(student.get("login") or "")
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "login": login, "password": password})


def _post_save_table(handler, g: dict) -> None:
    user = _require_user(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    student_id = str((payload or {}).get("id") or "")
    if user.get("role") == "student":
        student_id = user.get("student_id") or ""
    journal = g.get("journal")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        end = None
        if journal is not None and hasattr(journal, "parse_iso_date"):
            end = journal.parse_iso_date(str((student.get("schedule") or {}).get("endDate") or ""))
        if journal is not None and hasattr(journal, "clean_rows"):
            new_rows = journal.clean_rows(
                payload.get("rows"),
                keep_from_old=student.get("rows") if isinstance(student.get("rows"), list) else [],
                student_locked=user.get("role") == "student",
                end=end,
            )
        else:
            new_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        if user.get("role") == "student":
            old_rows = student.get("rows") if isinstance(student.get("rows"), list) else []
            for index, row in enumerate(new_rows):
                if index < len(old_rows) and isinstance(old_rows[index], dict) and isinstance(row, dict):
                    row["comment"] = str(old_rows[index].get("comment", "") or "")
        student["rows"] = new_rows
        if user.get("role") == "teacher" and payload.get("template") in ("once", "twice"):
            student["template"] = payload["template"]
        _save_data(g, data)
        saved = _public_one(g, student)
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "student": saved})


def _post_copy_table(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    source_id = str((payload or {}).get("sourceId") or "")
    target_id = str((payload or {}).get("targetId") or "")
    if not source_id or not target_id or source_id == target_id:
        _send_json(handler, {"ok": False, "error": "Выберите двух разных учеников"}, 400)
        return
    journal = g.get("journal")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        source = _find_student(g, data, source_id)
        target = _find_student(g, data, target_id)
        if not source or not target:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        if journal is not None and hasattr(journal, "copy_student_table"):
            journal.copy_student_table(source, target)
        _save_data(g, data)
        saved = _public_one(g, target)
        source_name = str(source.get("name") or "")
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "student": saved, "sourceName": source_name})


def _post_schedule(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    journal = g.get("journal")
    if journal is None:
        _send_json(handler, {"ok": False, "error": "Не получилось сохранить расписание"}, 500)
        return
    student_id = str((payload or {}).get("id") or "")
    start = journal.parse_iso_date(str(payload.get("startDate") or "")) if hasattr(journal, "parse_iso_date") else None
    template = "twice" if payload.get("template") == "twice" else "once"
    slots = journal.clean_slots(payload.get("slots"), template) if hasattr(journal, "clean_slots") else []
    requested_end, end_error = (journal.parse_end_date_value(payload.get("endDate")) if hasattr(journal, "parse_end_date_value") else (None, ""))
    if end_error:
        _send_json(handler, {"ok": False, "error": end_error}, 400)
        return
    if not start:
        _send_json(handler, {"ok": False, "error": "Укажите дату первого занятия"}, 400)
        return
    if not slots:
        _send_json(handler, {"ok": False, "error": "Укажите день недели и время"}, 400)
        return
    if template == "twice" and len(slots) < 2:
        _send_json(handler, {"ok": False, "error": "Для двух занятий в неделю нужны два разных дня"}, 400)
        return
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        fallback_end = journal.parse_iso_date(str((student.get("schedule") or {}).get("endDate") or "")) if hasattr(journal, "parse_iso_date") else None
        end, span_error = journal.resolve_schedule_end(start, slots, requested_end, fallback_end)
        if span_error:
            _send_json(handler, {"ok": False, "error": span_error}, 400)
            return
        student["template"] = template
        name = str(payload.get("name") or "").strip()
        if name:
            student["name"] = name
        grade = _clean_grade(g, payload.get("grade"))
        if grade:
            student["grade"] = grade
        student["schedule"] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "slots": slots,
        }
        if payload.get("regenerate", True) and hasattr(journal, "apply_schedule"):
            journal.apply_schedule(student, start, slots, template, end)
        _save_data(g, data)
        saved = _public_one(g, student)
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "student": saved})


def _post_progress(handler, g: dict) -> None:
    user = _require_user(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    journal = g.get("journal")
    student_id = str((payload or {}).get("studentId") or "")
    if user.get("role") == "student":
        student_id = user.get("student_id") or ""
    bank_id = str((payload or {}).get("bankId") or "")
    try:
        number = int((payload or {}).get("n"))
    except (TypeError, ValueError):
        _send_json(handler, {"ok": False, "error": "Некорректный номер задания"}, 400)
        return
    if journal is None or not hasattr(journal, "load_bank") or not journal.load_bank(bank_id):
        _send_json(handler, {"ok": False, "error": "Банк заданий не найден"}, 404)
        return
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        if user.get("role") == "student" and hasattr(journal, "has_task_answer") and journal.has_task_answer(student, bank_id, number):
            _send_json(handler, {"ok": False, "error": "Ответ уже сохранён. Изменить его нельзя."}, 409)
            return
        stats = journal.set_task_answer(student, bank_id, number, str(payload.get("answer") or ""))
        _save_data(g, data)
        color = journal.progress_color(stats["percent"]) if hasattr(journal, "progress_color") else ""
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "stats": stats, "statsColor": color})


def _post_upload(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    parsed = _parse_multipart(g, handler)
    if not parsed:
        _send_json(handler, {"ok": False, "error": "Файл слишком большой (до 20 МБ)"}, 400)
        return
    fields = parsed.get("fields") or {}
    uploaded = parsed.get("file")
    if not uploaded or not uploaded.get("data"):
        _send_json(handler, {"ok": False, "error": "Выберите файл"}, 400)
        return
    field = str(fields.get("field") or "theory")
    if field not in ("theory", "homework", "practice"):
        _send_json(handler, {"ok": False, "error": "Некорректное поле"}, 400)
        return
    student_id = str(fields.get("studentId") or "")
    try:
        row_index = int(fields.get("row"))
    except (TypeError, ValueError):
        _send_json(handler, {"ok": False, "error": "Некорректная строка"}, 400)
        return
    original = Path(uploaded.get("filename") or "material").name
    suffix = Path(original).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        _send_json(handler, {"ok": False, "error": "Можно прикрепить PDF, Word, презентацию или картинку"}, 400)
        return
    if field == "practice" and suffix != ".pdf":
        _send_json(handler, {"ok": False, "error": "В практику загрузите PDF с заданиями"}, 400)
        return
    stored = f"{uuid.uuid4().hex}{suffix}"
    dest_dir = _uploads_dir(g)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored
    dest.write_bytes(uploaded["data"])
    journal = g.get("journal")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            dest.unlink(missing_ok=True)
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        rows = student.get("rows") if isinstance(student.get("rows"), list) else []
        if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
            dest.unlink(missing_ok=True)
            _send_json(handler, {"ok": False, "error": "Строка не найдена"}, 400)
            return
        try:
            if journal is not None and hasattr(journal, "attach_row_file"):
                old_id = journal.attach_row_file(rows[row_index], field, stored, original)
            else:
                old_id = str(rows[row_index].get(f"{field}FileId") or "")
                rows[row_index][f"{field}FileId"] = stored
                rows[row_index][f"{field}FileName"] = original
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            _send_json(handler, {"ok": False, "error": str(exc)}, 400)
            return
        old_id = _safe_upload_id(g, str(old_id or ""))
        _save_data(g, data)
        if old_id:
            referenced = False
            check = g.get("upload_is_referenced")
            if callable(check):
                referenced = bool(check(data, old_id))
            if not referenced:
                (dest_dir / old_id).unlink(missing_ok=True)
        saved = _public_one(g, student)
    finally:
        _release_lock(acquired, lock)
    payload = {"ok": True, "student": saved}
    if field == "practice" and suffix == ".pdf":
        payload["needsImport"] = True
    _send_json(handler, payload)


def _post_import_pdf(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    student_id = str((payload or {}).get("studentId") or "")
    try:
        row_index = int((payload or {}).get("row"))
    except (TypeError, ValueError):
        _send_json(handler, {"ok": False, "error": "Некорректная строка"}, 400)
        return
    from_field = str((payload or {}).get("fromField") or "")
    url = str((payload or {}).get("url") or "").strip()
    pdf_import = g.get("pdf_import")
    journal = g.get("journal")
    pdf_bytes = b""
    source_name = "zadaniya.pdf"
    source_key = ""
    if url:
        if pdf_import is None or not hasattr(pdf_import, "download_pdf"):
            _send_json(handler, {"ok": False, "error": "Не получилось скачать PDF"}, 400)
            return
        try:
            pdf_bytes, source_name = pdf_import.download_pdf(url)
        except ValueError as exc:
            _send_json(handler, {"ok": False, "error": str(exc)}, 400)
            return
        source_key = pdf_import.canonical_source_url(url) if hasattr(pdf_import, "canonical_source_url") else url
    elif from_field == "practice":
        acquired, lock = _hold_lock(g)
        try:
            data = _load_data(g)
            student = _find_student(g, data, student_id)
            if not student:
                _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
                return
            rows = student.get("rows") if isinstance(student.get("rows"), list) else []
            if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
                _send_json(handler, {"ok": False, "error": "Строка не найдена"}, 400)
                return
            file_id = _safe_upload_id(g, str(rows[row_index].get("practiceFileId") or ""))
            file_name = str(rows[row_index].get("practiceFileName") or file_id)
        finally:
            _release_lock(acquired, lock)
        if not file_id or Path(file_id).suffix.lower() != ".pdf":
            _send_json(handler, {"ok": False, "error": "В этой строке нет PDF"}, 400)
            return
        path = _uploads_dir(g) / file_id
        if not path.is_file():
            _send_json(handler, {"ok": False, "error": "Файл не найден"}, 404)
            return
        pdf_bytes = path.read_bytes()
        source_name = file_name or file_id
        source_key = f"file:{file_id}"
    else:
        _send_json(handler, {"ok": False, "error": "Нужен PDF или ссылка на него"}, 400)
        return
    if pdf_import is None or not hasattr(pdf_import, "import_pdf_bytes"):
        _send_json(handler, {"ok": False, "error": "Не получилось разобрать PDF."}, 400)
        return
    try:
        bank_id = journal.pdf_bank_id(pdf_bytes) if journal is not None and hasattr(journal, "pdf_bank_id") else uuid.uuid4().hex
        parsed_bank = pdf_import.import_pdf_bytes(pdf_bytes, source_name, bank_id)
    except ValueError as exc:
        _send_json(handler, {"ok": False, "error": str(exc)}, 400)
        return
    except Exception as exc:
        _write_error(exc)
        _send_json(handler, {"ok": False, "error": "Не получилось разобрать PDF."}, 400)
        return
    attach = g.get("attach_pdf_bank")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        try:
            if callable(attach):
                bank = attach(data, student, row_index, b"", source_name, source_key, parsed=parsed_bank)
            else:
                if journal is not None and hasattr(journal, "save_bank"):
                    journal.save_bank(parsed_bank)
                rows = student.get("rows") if isinstance(student.get("rows"), list) else []
                rows[row_index]["bankId"] = parsed_bank["id"]
                rows[row_index]["importedSource"] = source_key
                bank = parsed_bank
            _save_data(g, data)
            saved = _public_one(g, student)
        except ValueError as exc:
            _send_json(handler, {"ok": False, "error": str(exc)}, 400)
            return
        except Exception as exc:
            _write_error(exc)
            _send_json(handler, {"ok": False, "error": "Не получилось сохранить задания из PDF."}, 400)
            return
    finally:
        _release_lock(acquired, lock)
    _send_json(
        handler,
        {
            "ok": True,
            "student": saved,
            "bankId": bank["id"],
            "total": len(bank.get("tasks") or []),
        },
    )


def _post_delete_file(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    field = str((payload or {}).get("field") or "")
    if field not in ("theory", "homework", "practice"):
        _send_json(handler, {"ok": False, "error": "Некорректное поле"}, 400)
        return
    student_id = str((payload or {}).get("studentId") or "")
    try:
        row_index = int((payload or {}).get("row"))
    except (TypeError, ValueError):
        _send_json(handler, {"ok": False, "error": "Некорректная строка"}, 400)
        return
    journal = g.get("journal")
    dest_dir = _uploads_dir(g)
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        student = _find_student(g, data, student_id)
        if not student:
            _send_json(handler, {"ok": False, "error": "Ученик не найден"}, 404)
            return
        rows = student.get("rows") if isinstance(student.get("rows"), list) else []
        if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
            _send_json(handler, {"ok": False, "error": "Строка не найдена"}, 400)
            return
        if journal is not None and hasattr(journal, "detach_row_file"):
            old_id = _safe_upload_id(g, str(journal.detach_row_file(rows[row_index], field, payload.get("fileId")) or ""))
        else:
            old_id = _safe_upload_id(g, str(rows[row_index].get(f"{field}FileId") or ""))
            rows[row_index][f"{field}FileId"] = ""
            rows[row_index][f"{field}FileName"] = ""
        _save_data(g, data)
        if old_id:
            referenced = False
            check = g.get("upload_is_referenced")
            if callable(check):
                referenced = bool(check(data, old_id))
            if not referenced:
                (dest_dir / old_id).unlink(missing_ok=True)
        saved = _public_one(g, student)
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "student": saved})


def _post_banks_delete(handler, g: dict) -> None:
    user = _require_teacher(handler)
    if user is None:
        return
    payload = _request_json(handler)
    if payload is None:
        return
    bank_id = str((payload or {}).get("id") or "")
    journal = g.get("journal")
    acquired, lock = _hold_lock(g)
    try:
        data = _load_data(g)
        error = ""
        if journal is not None and hasattr(journal, "purge_bank"):
            error = journal.purge_bank(data, bank_id) or ""
        else:
            error = "Не получилось удалить набор"
        if error:
            _send_json(handler, {"ok": False, "error": error}, 400)
            return
        _save_data(g, data)
        banks = journal.list_banks() if journal is not None and hasattr(journal, "list_banks") else []
        students = _students_payload(g, data).get("students") or []
    finally:
        _release_lock(acquired, lock)
    _send_json(handler, {"ok": True, "banks": banks, "students": students})


def _dispatch_post(handler, g: dict, path: str) -> bool:
    routes = {
        "/api/students": _post_create_student,
        "/api/students/delete": _post_delete_student,
        "/api/students/password": _post_student_password,
        "/api/table": _post_save_table,
        "/api/table/copy": _post_copy_table,
        "/api/schedule": _post_schedule,
        "/api/progress": _post_progress,
        "/api/upload": _post_upload,
        "/api/import-pdf": _post_import_pdf,
        "/api/file/delete": _post_delete_file,
        "/api/banks/delete": _post_banks_delete,
    }
    action = routes.get(path)
    if action is None:
        return False
    action(handler, g)
    return True


def install(g: dict) -> bool:
    handler_cls = _find_handler(g)
    if handler_cls is None:
        return False
    orig_get = handler_cls.do_GET
    orig_post = getattr(handler_cls, "do_POST", None)
    _wrap_read_json(handler_cls)
    _wrap_save_data(g)
    _wrap_handler_send_json(handler_cls)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/api/students":
            return orig_get(self)
        try:
            user = self._user() if hasattr(self, "_user") else None
            if not user:
                _send_json(self, {"ok": False, "error": "Нужно войти"}, 401)
                return
            data = _locked_data(g)
            if user.get("role") == "teacher":
                _send_json(self, _students_payload(g, data))
                return
            student = _find_student(g, data, user.get("student_id", ""))
            payload = _public_one(g, student)
            _send_json(self, {"students": [payload] if payload else []})
        except Exception as exc:
            _write_error(exc)
            try:
                _send_json(self, {"ok": False, "error": "Не получилось открыть журнал"}, 500)
            except Exception:
                return

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if _dispatch_post(self, g, path):
                return
            if orig_post:
                orig_post(self)
        except Exception as exc:
            _write_error(exc)
            if _headers_sent(self):
                return
            try:
                _send_json(self, {"ok": False, "error": "Не получилось выполнить запрос"}, 500)
            except Exception:
                return

    handler_cls.do_GET = do_GET
    handler_cls.do_POST = do_POST
    return True
