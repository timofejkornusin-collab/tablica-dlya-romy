# -*- coding: utf-8 -*-
"""Safe GET /api/students for production server.py that we do not replace."""

from __future__ import annotations

import json
import traceback
from pathlib import Path


ERROR_LOG = Path("/tmp/journal-students-error.log")


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


def install(g: dict) -> bool:
    handler_cls = _find_handler(g)
    if handler_cls is None:
        return False
    orig_get = handler_cls.do_GET

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/api/students":
            return orig_get(self)
        try:
            user = self._user() if hasattr(self, "_user") else None
            if not user:
                _send_json(self, {"ok": False, "error": "Нужно войти"}, 401)
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
            finally:
                if acquired:
                    try:
                        lock.release()
                    except Exception:
                        pass
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

    handler_cls.do_GET = do_GET
    return True
