# -*- coding: utf-8 -*-
"""Safe GET /api/students for production server.py that we do not replace."""

from __future__ import annotations

import contextvars
import json
import traceback
from pathlib import Path


ERROR_LOG = Path("/tmp/journal-students-error.log")
_grade_job = contextvars.ContextVar("journal_grade_job", default=None)


def _write_error(exc: BaseException | None = None) -> None:
    try:
        text = traceback.format_exc() if exc is None else "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        ERROR_LOG.write_text(text, encoding="utf-8")
    except Exception:
        return


def _send_json(handler, payload, status: int = 200) -> None:
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")
    except Exception as exc:
        _write_error(exc)
        body = json.dumps({"ok": False, "error": "Не получилось отдать данные"}, ensure_ascii=False).encode("utf-8")
        status = 500
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.wfile.write(body)


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
    for item in data.get("students") or []:
        if isinstance(item, dict) and item.get("id") == student_id:
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


def _locked_data(g: dict) -> dict:
    lock = g.get("DATA_LOCK")
    acquired = False
    try:
        if lock is not None and hasattr(lock, "acquire"):
            try:
                acquired = bool(lock.acquire(True, 3))
            except TypeError:
                lock.acquire()
                acquired = True
        return _load_data(g)
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass


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
        return {}
    return data if isinstance(data, dict) else {}


def _clean_grade(g: dict, raw) -> str:
    journal = g.get("journal")
    cleaner = getattr(journal, "clean_grade", None) if journal is not None else None
    if callable(cleaner):
        try:
            return str(cleaner(raw) or "")
        except Exception:
            pass
    return " ".join(str(raw or "").split())[:24]


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


def _persist_student_grade(g: dict, path: str, payload) -> None:
    if not isinstance(payload, dict):
        return
    if not _clean_grade(g, payload.get("grade")):
        return
    lock = g.get("DATA_LOCK")
    acquired = False
    try:
        if lock is not None and hasattr(lock, "acquire"):
            try:
                acquired = bool(lock.acquire(True, 3))
            except TypeError:
                lock.acquire()
                acquired = True
        data = _load_data(g)
        if _apply_grade_to_data(g, data, path, payload):
            _save_data(g, data)
    except Exception as exc:
        _write_error(exc)
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass


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


def install(g: dict) -> bool:
    handler_cls = _find_handler(g)
    if handler_cls is None:
        return False
    orig_get = handler_cls.do_GET
    orig_post = getattr(handler_cls, "do_POST", None)
    _wrap_read_json(handler_cls)
    _wrap_save_data(g)

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
        if path == "/api/banks/delete":
            try:
                user = self._user() if hasattr(self, "_user") else None
                if not user:
                    _send_json(self, {"ok": False, "error": "Нужно войти"}, 401)
                    return
                if user.get("role") != "teacher":
                    _send_json(self, {"ok": False, "error": "Набор удаляет учитель"}, 403)
                    return
                payload = _request_json(self)
                if payload is None:
                    return
                bank_id = str((payload or {}).get("id") or "")
                journal = g.get("journal")
                lock = g.get("DATA_LOCK")
                acquired = False
                try:
                    if lock is not None and hasattr(lock, "acquire"):
                        try:
                            acquired = bool(lock.acquire(True, 3))
                        except TypeError:
                            lock.acquire()
                            acquired = True
                    data = _load_data(g)
                    error = ""
                    if journal is not None and hasattr(journal, "purge_bank"):
                        error = journal.purge_bank(data, bank_id) or ""
                    else:
                        error = "Не получилось удалить набор"
                    if error:
                        _send_json(self, {"ok": False, "error": error}, 400)
                        return
                    _save_data(g, data)
                    banks = journal.list_banks() if journal is not None and hasattr(journal, "list_banks") else []
                    students = _students_payload(g, data).get("students") or []
                finally:
                    if acquired:
                        try:
                            lock.release()
                        except Exception:
                            pass
                _send_json(self, {"ok": True, "banks": banks, "students": students})
            except Exception as exc:
                _write_error(exc)
                try:
                    _send_json(self, {"ok": False, "error": "Не получилось удалить набор"}, 500)
                except Exception:
                    return
            return
        if path in ("/api/students", "/api/schedule"):
            job = {"path": path, "payload": None}
            token = _grade_job.set(job)
            try:
                if orig_post:
                    orig_post(self)
                payload = job.get("payload")
                if not isinstance(payload, dict):
                    payload = getattr(self, "_journal_json_cache", None)
                _persist_student_grade(g, path, payload)
            finally:
                _grade_job.reset(token)
            return
        if orig_post:
            return orig_post(self)
        return None

    handler_cls.do_GET = do_GET
    handler_cls.do_POST = do_POST
    return True
