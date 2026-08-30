#!/usr/bin/env python3
"""Safe production update: keeps the customized index.html and server.py.

Run on the server as:

    python3 /tmp/journal-release/tools/deploy-production.py

Do not run this through bash. Windows often saves files with CRLF;
python3 still executes them, bash does not.

This script never replaces production server.py and never overwrites
index.html wholesale: it only patches cache-buster query strings.
"""

from __future__ import annotations

import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

STAGE = Path(os.environ.get("JOURNAL_STAGE", "/tmp/journal-release"))
APP_ROOT = Path(os.environ.get("JOURNAL_APP_ROOT", "/var/www/journal"))
STATIC_ROOT = APP_ROOT / "static"
BACKUP_ROOT = Path(os.environ.get("JOURNAL_BACKUP_ROOT", "/var/backups"))
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP = BACKUP_ROOT / f"journal-{STAMP}"
LOCAL_URL = os.environ.get("JOURNAL_LOCAL_URL", "http://127.0.0.1:8765")
SITE_URL = os.environ.get("JOURNAL_SITE_URL", "https://rusklasst.ru/")
SKIP_RESTART = os.environ.get("JOURNAL_SKIP_RESTART") == "1"
SKIP_HEALTHCHECK = os.environ.get("JOURNAL_SKIP_HEALTHCHECK") == "1"
RESTART_SLEEP = int(os.environ.get("JOURNAL_RESTART_SLEEP", "75"))
START_SLEEP = int(os.environ.get("JOURNAL_START_SLEEP", "6"))

REQUIRED = (
    "journal.py",
    "pdf_import.py",
    "static/app.js",
    "static/styles.css",
    "static/mobile.css",
    "static/practice-scales.js",
    "static/practice-scales.css",
    "static/practice-page.js",
    "tools/production_students_safety.py",
)

APP_MARKERS = (
    "copy-table-btn",
    "lesson-status-btn",
    "practice-summary",
    "restorePracticeScroll",
    "keepScroll",
    "applyCopiedTable",
    "applyCopiedRow",
    "row-copy-btn",
    "bumpSaveEpoch",
    "keepRicher",
    "syncStartDateWeekday",
    "importLinkedPdfs",
    "ensureEndDateField",
    "trimRowsToScheduleEnd",
    "extraLessonRow",
    "startErrorHtml",
    "hideUnwantedLabels",
    "setPageSubtitle",
    "bank-picker-toggle",
    "bank-picker-choice",
    "bank-picker-name",
    "bank-delete",
    "deletePracticeBank",
    "practice-open-hint",
    "practice-upload",
    "bank-picker-layer",
    "bank-picker-list",
    "theoryFiles",
    "rowTheoryFiles",
    "renderStudentTextCell",
    "attach-file-label",
    "updateLogoutButton",
)

CACHE_BUSTERS = {
    r'styles\.css(?:\?v=[^"]*)?': "styles.css?v=list-nowrap1",
    r'mobile\.css(?:\?v=[^"]*)?': "mobile.css?v=theory-grow1",
    r'app\.js(?:\?v=[^"]*)?': "app.js?v=logout-list1",
    r'practice-page\.js(?:\?v=[^"]*)?': "practice-page.js?v=2",
    r'practice-scales\.css(?:\?v=[^"]*)?': "practice-scales.css?v=2",
    r'practice-scales\.js(?:\?v=[^"]*)?': "practice-scales.js?v=2",
}


def fail(message: str, code: int = 1) -> None:
    print(message)
    raise SystemExit(code)


def curl_code(url: str, timeout: int = 8) -> str:
    result = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or "000").strip() or "000"


def diagnose_students() -> None:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            "20",
            "-D",
            "-",
            "-o",
            "/tmp/journal-students-body.txt",
            "-w",
            "\nhttp_code=%{http_code}\n",
            LOCAL_URL + "/api/students",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    print("students-curl:\n%s%s" % ((result.stdout or "")[:1500], (result.stderr or "")[:800]))
    log = Path("/tmp/journal-students-error.log")
    if log.is_file():
        print("students-error.log:\n%s" % log.read_text(encoding="utf-8", errors="replace")[:2500])
    journalctl = subprocess.run(
        ["journalctl", "-u", "journal", "-n", "50", "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
    )
    print("journalctl:\n%s" % ((journalctl.stdout or journalctl.stderr or "")[:2500]))


def wait_for_students() -> str:
    last = "000"
    for attempt in range(8):
        last = curl_code(LOCAL_URL + "/api/students", timeout=20)
        print("api try %s: %s" % (attempt + 1, last))
        if last in ("200", "401"):
            return last
        time.sleep(2)
    diagnose_students()
    return last


def curl_body(url: str, timeout: int = 8) -> str:
    result = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), url],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def patch_index(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern, replacement in CACHE_BUSTERS.items():
        text = re.sub(pattern, replacement, text)
    path.write_text(text, encoding="utf-8")


APPLY_SCHEDULE_RE = re.compile(
    r"journal\.apply_schedule\(\s*student\s*,\s*start\s*,\s*slots\s*,\s*template\s*\)"
)
APPLY_SCHEDULE_WITH_END = (
    "journal.apply_schedule(student, start, slots, template, "
    "journal.end_from_payload(locals().get('payload'), start, slots, student.get('schedule')))"
)
UNSAFE_END_FROM_PAYLOAD = (
    "journal.end_from_payload(payload, start, slots, student.get('schedule'))"
)
SAFE_END_FROM_PAYLOAD = (
    "journal.end_from_payload(locals().get('payload'), start, slots, student.get('schedule'))"
)
STUDENTS_LIST_RE = re.compile(
    r'\{\s*"students"\s*:\s*\[\s*(?:journal\.)?public_student\(\s*(?P<var>\w+)\s*\)\s+'
    r'for\s+(?P=var)\s+in\s+data(?:\.get\(\s*["\']students["\']\s*\)|\[["\']students["\']\])'
    r'(?:\s+if\s+(?:journal\.)?public_student\(\s*(?P=var)\s*\))?\s*\]\s*\}'
)
JSON_DUMPS_RE = re.compile(
    r'json\.dumps\(\s*payload\s*,\s*ensure_ascii\s*=\s*False\s*\)\.encode\(\s*["\']utf-8["\']\s*\)'
)
SAFE_JSON_DUMPS = 'json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")'


SAFETY_BEGIN = "# journal-students-safety-begin"
SAFETY_END = "# journal-students-safety-end"
SAFETY_INSTALL = """

%s
try:
    import sys as _journal_sys
    from pathlib import Path as _journal_Path
    _journal_root = str(_journal_Path(__file__).resolve().parent)
    if _journal_root not in _journal_sys.path:
        _journal_sys.path.insert(0, _journal_root)
    import production_students_safety as _journal_students_safety
    _journal_students_safety.install(globals())
except Exception:
    pass
%s
""" % (SAFETY_BEGIN, SAFETY_END)
MAIN_GUARD_RE = re.compile(r"\nif __name__ == [\"']__main__[\"']:")


def strip_server_safety(text: str) -> str:
    return re.sub(
        r"\n*" + re.escape(SAFETY_BEGIN) + r".*?" + re.escape(SAFETY_END) + r"\n?",
        "\n",
        text,
        flags=re.S,
    )


def insert_safety_block(text: str) -> str:
    text = strip_server_safety(text)
    match = MAIN_GUARD_RE.search(text)
    if match:
        return text[: match.start()] + SAFETY_INSTALL + text[match.start() :]
    return text.rstrip() + SAFETY_INSTALL


def patch_server(path: Path) -> None:
    """Keep production server.py, but take over GET /api/students safely."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace(UNSAFE_END_FROM_PAYLOAD, SAFE_END_FROM_PAYLOAD)
    text = text.replace(
        'journal.end_from_payload(payload, start, slots, student.get("schedule"))',
        SAFE_END_FROM_PAYLOAD,
    )
    text, _count = APPLY_SCHEDULE_RE.subn(APPLY_SCHEDULE_WITH_END, text)
    text, _students = STUDENTS_LIST_RE.subn("journal.public_students_payload(data.get('students'))", text)
    text, _dumps = JSON_DUMPS_RE.subn(SAFE_JSON_DUMPS, text)
    for old, new in (
        (
            'field in ("practice", "theory", "homework") and suffix == ".pdf"',
            'field == "practice" and suffix == ".pdf"',
        ),
        (
            "field in ('practice', 'theory', 'homework') and suffix == '.pdf'",
            'field == "practice" and suffix == ".pdf"',
        ),
        (
            'field in ("theory", "homework", "practice") and suffix == ".pdf"',
            'field == "practice" and suffix == ".pdf"',
        ),
        (
            'suffix == ".pdf" and field in ("practice", "theory", "homework")',
            'field == "practice" and suffix == ".pdf"',
        ),
        (
            'from_field in ("homework", "practice", "theory")',
            'from_field == "practice"',
        ),
        (
            'from_field in ("practice", "theory", "homework")',
            'from_field == "practice"',
        ),
        (
            'if field == "practice" or not str(rows[row_index].get("bankId") or ""):',
            'if field == "practice":',
        ),
        (
            "if field == 'practice' or not str(rows[row_index].get('bankId') or ''):",
            'if field == "practice":',
        ),
        (
            "old_id = safe_upload_id(str(rows[row_index].get(f\"{field}FileId\") or \"\"))\n"
            "            rows[row_index][f\"{field}FileId\"] = stored\n"
            "            rows[row_index][f\"{field}FileName\"] = original",
            "old_id = journal.attach_row_file(rows[row_index], field, stored, original)\n"
            "            old_id = safe_upload_id(str(old_id or \"\"))",
        ),
        (
            "old_id = safe_upload_id(str(rows[row_index].get(f\"{field}FileId\") or \"\"))\n"
            "            rows[row_index][f\"{field}FileId\"] = \"\"\n"
            "            rows[row_index][f\"{field}FileName\"] = \"\"",
            "old_id = safe_upload_id(str(journal.detach_row_file(rows[row_index], field, payload.get(\"fileId\")) or \"\"))",
        ),
    ):
        text = text.replace(old, new)
    text = insert_safety_block(text)
    path.write_text(text, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def install_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".new")
    shutil.copyfile(source, tmp)
    os.chmod(tmp, 0o644)
    tmp.replace(target)


def copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def restore_files() -> None:
    shutil.copy2(BACKUP / "journal.py", APP_ROOT / "journal.py")
    shutil.copy2(BACKUP / "pdf_import.py", APP_ROOT / "pdf_import.py")
    if (BACKUP / "server.py").exists():
        shutil.copy2(BACKUP / "server.py", APP_ROOT / "server.py")
    for item in (BACKUP / "static").iterdir():
        shutil.copy2(item, STATIC_ROOT / item.name)
    students = BACKUP / "data" / "students.json"
    if students.exists():
        (APP_ROOT / "data").mkdir(parents=True, exist_ok=True)
        shutil.copy2(students, APP_ROOT / "data" / "students.json")


def restart_on_8765() -> None:
    if SKIP_RESTART:
        print("Пропуск перезапуска (проверка без systemd).")
        return
    subprocess.run(["systemctl", "stop", "journal"], check=False)
    subprocess.run(
        ["pkill", "-9", "-f", "/var/www/journal/.venv/bin/python.*server.py"],
        check=False,
    )
    subprocess.run(["fuser", "-k", "8765/tcp", "8766/tcp", "8767/tcp"], check=False)
    print("Порт освобождается. Ждите %s секунд и ничего не нажимайте." % RESTART_SLEEP)
    time.sleep(RESTART_SLEEP)
    started = subprocess.run(["systemctl", "start", "journal"], check=False)
    if started.returncode != 0:
        fail("ОШИБКА: systemctl start journal не удался.")
    time.sleep(START_SLEEP)


def require_stage_files() -> None:
    for relative in REQUIRED:
        path = STAGE / relative
        if not path.is_file() or path.stat().st_size == 0:
            fail("ОШИБКА: во временной папке нет %s. Сайт не изменён." % relative)


def require_python_and_markers() -> None:
    try:
        py_compile.compile(str(STAGE / "journal.py"), doraise=True)
        py_compile.compile(str(STAGE / "pdf_import.py"), doraise=True)
        py_compile.compile(str(STAGE / "tools" / "production_students_safety.py"), doraise=True)
    except py_compile.PyCompileError:
        fail("ОШИБКА: проверка Python не прошла. Сайт не изменён.")
    app_js = (STAGE / "static" / "app.js").read_text(encoding="utf-8", errors="replace")
    missing = [marker for marker in APP_MARKERS if marker not in app_js]
    if missing:
        fail("ОШИБКА: загружена не та версия app.js. Сайт не изменён.")
    page_js = (STAGE / "static" / "practice-page.js").read_text(encoding="utf-8", errors="replace")
    if "scrollTop = 0" in page_js or "scrollTop=0" in page_js:
        fail("ОШИБКА: practice-page.js снова сбрасывает прокрутку. Сайт не изменён.")
    journal_py = (STAGE / "journal.py").read_text(encoding="utf-8", errors="replace")
    if (
        "end_date_from_request_payload" not in journal_py
        or "public_students_payload" not in journal_py
        or "public_student_summary" not in journal_py
        or "purge_bank" not in journal_py
        or "attach_row_file" not in journal_py
        or "MAX_THEORY_FILES" not in journal_py
    ):
        fail("ОШИБКА: загружена не та версия journal.py. Сайт не изменён.")


def backup_current() -> None:
    (BACKUP / "static").mkdir(parents=True, exist_ok=True)
    (BACKUP / "data").mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(APP_ROOT / "journal.py", BACKUP / "journal.py")
        shutil.copy2(APP_ROOT / "pdf_import.py", BACKUP / "pdf_import.py")
        copy_if_exists(APP_ROOT / "server.py", BACKUP / "server.py")
        shutil.copy2(STATIC_ROOT / "index.html", BACKUP / "static" / "index.html")
        shutil.copy2(STATIC_ROOT / "app.js", BACKUP / "static" / "app.js")
        shutil.copy2(STATIC_ROOT / "styles.css", BACKUP / "static" / "styles.css")
        shutil.copy2(STATIC_ROOT / "mobile.css", BACKUP / "static" / "mobile.css")
    except OSError:
        fail("ОШИБКА: резервная копия не создана. Сайт не изменён.")
    copy_if_exists(STATIC_ROOT / "practice-scales.js", BACKUP / "static" / "practice-scales.js")
    copy_if_exists(STATIC_ROOT / "practice-scales.css", BACKUP / "static" / "practice-scales.css")
    copy_if_exists(STATIC_ROOT / "practice-page.js", BACKUP / "static" / "practice-page.js")
    copy_if_exists(APP_ROOT / "data" / "students.json", BACKUP / "data" / "students.json")


def install_stage() -> None:
    try:
        install_file(STAGE / "journal.py", APP_ROOT / "journal.py")
        install_file(STAGE / "pdf_import.py", APP_ROOT / "pdf_import.py")
        install_file(STAGE / "static" / "app.js", STATIC_ROOT / "app.js")
        install_file(STAGE / "static" / "styles.css", STATIC_ROOT / "styles.css")
        install_file(STAGE / "static" / "mobile.css", STATIC_ROOT / "mobile.css")
        install_file(STAGE / "static" / "practice-scales.js", STATIC_ROOT / "practice-scales.js")
        install_file(STAGE / "static" / "practice-scales.css", STATIC_ROOT / "practice-scales.css")
        install_file(STAGE / "static" / "practice-page.js", STATIC_ROOT / "practice-page.js")
        install_file(
            STAGE / "tools" / "production_students_safety.py",
            APP_ROOT / "production_students_safety.py",
        )
        patch_index(STATIC_ROOT / "index.html")
        patch_server(APP_ROOT / "server.py")
    except Exception:
        restore_files()
        fail("ОШИБКА: файлы не установлены. Восстановлена прежняя версия.")


def verify_live() -> tuple[str, str, str]:
    installed_app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8", errors="replace")
    installed_index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8", errors="replace")
    app_marker = "1" if "restorePracticeScroll" in installed_app else "0"
    index_marker = "1" if "logout-list1" in installed_index else "0"

    if SKIP_HEALTHCHECK:
        local_code = "200"
        api_code = "skip"
        python_8766 = "000"
        site_code = "skip"
    else:
        local_code = curl_code(LOCAL_URL + "/")
        live_app = curl_body(LOCAL_URL + "/app.js")
        live_index = curl_body(LOCAL_URL + "/")
        app_marker = str(live_app.count("restorePracticeScroll"))
        index_marker = str(live_index.count("logout-list1"))
        api_code = wait_for_students()
        python_8766 = curl_code("http://127.0.0.1:8766/", timeout=3)
        site_code = curl_code(SITE_URL, timeout=10)

    print("Проверка: site=%s app=%s index=%s api=%s" % (local_code, app_marker, index_marker, api_code))
    if local_code != "200" or app_marker == "0" or index_marker == "0":
        print("ПРОВЕРКА НЕ ПРОШЛА. ВОССТАНАВЛИВАЮ ПРЕЖНЮЮ ВЕРСИЮ.")
        restore_files()
        restart_on_8765()
        rollback_code = "skip" if SKIP_HEALTHCHECK else curl_code(LOCAL_URL + "/")
        fail("ОТКАТ ЗАВЕРШЁН. python8765:%s" % rollback_code)
    if not SKIP_HEALTHCHECK and api_code not in ("200", "401"):
        print("ПРОВЕРКА НЕ ПРОШЛА: /api/students=%s. Новую версию оставляю, откат списка не чинит." % api_code)
        fail("ОСТАВЛЕНО БЕЗ ОТКАТА. python8765:%s api:%s" % (local_code, api_code))

    if SKIP_HEALTHCHECK:
        python_8766 = "000"
        site_code = "skip"
    return local_code, python_8766, site_code


def main() -> None:
    require_stage_files()
    if not SKIP_HEALTHCHECK:
        before_code = curl_code(LOCAL_URL + "/")
        if before_code != "200":
            fail("ОШИБКА: сайт до обновления не отвечает на порту 8765. Обновление отменено.")
    require_python_and_markers()
    backup_current()
    install_stage()
    restart_on_8765()
    local_code, python_8766, site_code = verify_live()
    print("ГОТОВО. ВСЕ ИЗМЕНЕНИЯ УСТАНОВЛЕНЫ.")
    print("Резервная копия: %s" % BACKUP)
    print("python8765:%s" % local_code)
    print("python8766:%s" % python_8766)
    print("site:%s" % site_code)


if __name__ == "__main__":
    main()
