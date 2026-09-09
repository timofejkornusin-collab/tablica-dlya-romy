#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал занятий: таблицы учеников и ссылка для телефона."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import journal
import pdf_import

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = ROOT / "data"
TOOLS_DIR = ROOT / "tools"
DATA_FILE = DATA_DIR / "students.json"
AUTH_FILE = DATA_DIR / "auth.json"
UPLOADS_DIR = DATA_DIR / "uploads"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
CLOUDFLARED = TOOLS_DIR / "cloudflared.exe"
HOST = "0.0.0.0"
START_PORT = 8765
COOKIE_NAME = "journal_session"
CLOUDFLARED_URLS = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://github.com/cloudflare/cloudflared/releases/download/2025.8.1/cloudflared-windows-amd64.exe",
)

DATA_LOCK = threading.Lock()
SESSION_LOCK = threading.Lock()
SESSIONS: dict[str, dict] = {}
PUBLIC_URL = ""
TUNNEL_ERROR = ""
TUNNEL_PROC: subprocess.Popen | None = None
STUDENT_SITE_URL = "https://rusklasst.ru"
EPHEMERAL_SHARE_RE = re.compile(r"pinggy|trycloudflare\.com|ngrok|loca\.lt", re.I)
WIFI_NAME_CACHE = ""
LAN_IP_CACHE = ""
LAN_IPS_CACHE: list[str] = []
LAN_INFO_AT = 0.0
LOGIN_HITS: dict[str, list[float]] = {}

RU_TO_LAT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def slug_login(name: str) -> str:
    raw = []
    for char in (name or "").strip().lower():
        if char in RU_TO_LAT:
            raw.append(RU_TO_LAT[char])
        elif char.isalnum():
            raw.append(char)
    login = "".join(raw) or "uchenik"
    return login[:40]


def generate_password() -> str:
    chars = [secrets.choice(PASSWORD_ALPHABET) for _ in range(8)]
    return "".join(chars[:4]) + "-" + "".join(chars[4:])


def is_loopback(host: str) -> bool:
    value = (host or "").strip().lower().strip("[]")
    if value in ("127.0.0.1", "::1", "localhost"):
        return True
    if value.startswith("::ffff:") and value.rsplit(":", 1)[-1] == "127.0.0.1":
        return True
    return value.startswith("127.")


PUBLIC_HOSTS = ("rusklasst.ru", "www.rusklasst.ru")


def request_hostname(handler) -> str:
    raw = (handler.headers.get("Host") or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        if end > 0:
            return raw[1:end]
    if raw.count(":") == 1:
        return raw.rsplit(":", 1)[0]
    return raw


def is_proxied_request(handler) -> bool:
    if handler.headers.get("X-Forwarded-For"):
        return True
    if handler.headers.get("X-Real-IP"):
        return True
    if handler.headers.get("X-Forwarded-Proto"):
        return True
    return request_hostname(handler) in PUBLIC_HOSTS


def allow_local_teacher(handler) -> bool:
    """Учитель без логина только в локальном приложении, не через nginx."""
    if os.environ.get("JOURNAL_DISABLE_LOCAL_TEACHER") == "1":
        return False
    if os.environ.get("INVOCATION_ID"):
        return False
    if os.environ.get("JOURNAL_PUBLIC_URL", "").strip():
        return False
    if is_proxied_request(handler):
        return False
    host = request_hostname(handler)
    if host in PUBLIC_HOSTS:
        return False
    if host and host not in ("127.0.0.1", "localhost", "::1"):
        return False
    return is_loopback(handler.client_address[0])


def request_client_ip(handler) -> str:
    peer = handler.client_address[0]
    forwarded = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    real_ip = (handler.headers.get("X-Real-IP") or "").strip()
    if is_proxied_request(handler) or (is_loopback(peer) and (forwarded or real_ip)):
        return forwarded or real_ip or peer
    return peer


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return salt, digest


def check_password(password: str, salt: str, digest: str) -> bool:
    if not salt or not digest:
        return False
    _, got = hash_password(password, salt)
    return hmac.compare_digest(got, digest)


def default_data() -> dict:
    return {"students": []}


def default_auth() -> dict:
    salt, digest = hash_password("учитель")
    return {
        "teacher_login": "учитель",
        "teacher_salt": salt,
        "teacher_password_hash": digest,
        "teacher_password_is_initial": True,
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return fallback
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return raw if isinstance(raw, dict) else fallback


def load_auth() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not AUTH_FILE.exists():
        auth = default_auth()
        atomic_write(AUTH_FILE, auth)
        return auth
    auth = load_json(AUTH_FILE, {})
    if not auth.get("teacher_login") or not auth.get("teacher_password_hash"):
        auth = default_auth()
        atomic_write(AUTH_FILE, auth)
    return auth


def save_auth(auth: dict) -> None:
    atomic_write(AUTH_FILE, auth)


def load_data() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        atomic_write(DATA_FILE, default_data())
        return default_data()
    raw = load_json(DATA_FILE, default_data())
    if not isinstance(raw.get("students"), list):
        return default_data()
    return raw


def save_data(data: dict) -> None:
    atomic_write(DATA_FILE, {"students": data.get("students", [])})


def migrate_students() -> list[str]:
    notes = []
    with DATA_LOCK:
        data = load_data()
        used = {str(item.get("login", "")).casefold() for item in data["students"]}
        used.add(load_auth()["teacher_login"].casefold())
        changed = False
        for student in data["students"]:
            if not isinstance(student, dict):
                continue
            if not student.get("id"):
                student["id"] = str(uuid.uuid4())
                changed = True
            login = str(student.get("login") or "").strip()
            if not login:
                base = slug_login(str(student.get("name") or "uchenik"))
                login = base
                suffix = 2
                while login.casefold() in used:
                    login = f"{base}{suffix}"
                    suffix += 1
                student["login"] = login
                used.add(login.casefold())
                changed = True
            if not student.get("password_hash"):
                password = str(student["login"])
                salt, digest = hash_password(password)
                student["password_salt"] = salt
                student["password_hash"] = digest
                student["password_is_initial"] = True
                notes.append(
                    f"Ученик «{student.get('name')}»: логин {student['login']}, пароль {password}"
                )
                changed = True
        if changed:
            save_data(data)
    return notes


def public_student(student: dict | None) -> dict | None:
    return journal.public_student(student)


def find_student(data: dict, student_id: str) -> dict | None:
    for student in data["students"]:
        if isinstance(student, dict) and student.get("id") == student_id:
            return student
    return None


def login_taken(login: str, skip_id: str | None = None) -> bool:
    folded = login.casefold()
    auth = load_auth()
    if auth["teacher_login"].casefold() == folded:
        return True
    data = load_data()
    for student in data["students"]:
        if skip_id and student.get("id") == skip_id:
            continue
        if str(student.get("login", "")).casefold() == folded:
            return True
    return False


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
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


def safe_upload_id(raw: str) -> str:
    name = Path(str(raw or "")).name
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,80}", name):
        return ""
    suffix = Path(name).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        return ""
    return name


def row_upload_ids(rows) -> set[str]:
    result: set[str] = set()
    if not isinstance(rows, list):
        return result
    id_keys = tuple(key for key in journal.FILE_KEYS if key.endswith("FileId"))
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_ids = list(journal.iter_row_file_ids(row)) if hasattr(journal, "iter_row_file_ids") else []
        if not raw_ids:
            for key in id_keys:
                raw_ids.append(str(row.get(key) or ""))
        for raw in raw_ids:
            file_id = safe_upload_id(str(raw or ""))
            if file_id:
                result.add(file_id)
    return result


def upload_is_referenced(data: dict, file_id: str) -> bool:
    safe_id = safe_upload_id(file_id)
    if not safe_id:
        return False
    for student in data.get("students") or []:
        if isinstance(student, dict) and safe_id in row_upload_ids(student.get("rows")):
            return True
    return False


def parse_multipart(headers, body: bytes) -> dict:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"boundary=([^;]+)", content_type, re.I)
    if not match:
        return {"fields": {}, "file": None}
    boundary = match.group(1).strip().strip('"').encode("utf-8")
    fields: dict[str, str] = {}
    uploaded = None
    for raw_part in body.split(b"--" + boundary):
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


def attach_pdf_bank(
    data: dict,
    student: dict,
    row_index: int,
    pdf_bytes: bytes,
    source_name: str,
    source_key: str,
    parsed: dict | None = None,
) -> dict:
    rows = student.get("rows") if isinstance(student.get("rows"), list) else []
    if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
        raise ValueError("Строка не найдена")
    bank = parsed or pdf_import.import_pdf_bytes(pdf_bytes, source_name, journal.pdf_bank_id(pdf_bytes))
    journal.save_bank(bank)
    row = rows[row_index]
    row["bankId"] = bank["id"]
    row["importedSource"] = source_key
    return bank


def too_many_logins(ip: str) -> bool:
    now = time.time()
    with SESSION_LOCK:
        hits = [stamp for stamp in LOGIN_HITS.get(ip, []) if now - stamp < 600]
        LOGIN_HITS[ip] = hits
        return len(hits) >= 12


def mark_login_fail(ip: str) -> None:
    with SESSION_LOCK:
        LOGIN_HITS.setdefault(ip, []).append(time.time())


def session_file() -> Path:
    return DATA_DIR / "sessions.json"


def _session_alive(payload: dict) -> bool:
    if not isinstance(payload, dict) or payload.get("local"):
        return False
    created = payload.get("created")
    try:
        created_at = float(created or 0)
    except (TypeError, ValueError):
        created_at = 0.0
    if created_at and (time.time() - created_at) > SESSION_MAX_AGE:
        return False
    return payload.get("role") in ("teacher", "student")


def load_sessions() -> None:
    path = session_file()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    loaded = {
        str(token): payload
        for token, payload in raw.items()
        if token and _session_alive(payload)
    }
    with SESSION_LOCK:
        SESSIONS.update(loaded)


def save_sessions() -> None:
    path = session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with SESSION_LOCK:
        snapshot = {
            token: payload
            for token, payload in SESSIONS.items()
            if _session_alive(payload)
        }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def new_session(payload: dict) -> str:
    token = secrets.token_urlsafe(24)
    record = dict(payload)
    record["created"] = time.time()
    with SESSION_LOCK:
        SESSIONS[token] = record
    save_sessions()
    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    with SESSION_LOCK:
        payload = SESSIONS.get(token)
    if payload is None:
        load_sessions()
        with SESSION_LOCK:
            payload = SESSIONS.get(token)
    if payload is None:
        return None
    if not _session_alive(payload):
        drop_session(token)
        return None
    return payload


def drop_session(token: str | None) -> None:
    if not token:
        return
    with SESSION_LOCK:
        SESSIONS.pop(token, None)
    save_sessions()


def lan_ip() -> str:
    refresh_network_info()
    return LAN_IP_CACHE or "127.0.0.1"


def lan_ips() -> list[str]:
    refresh_network_info()
    return LAN_IPS_CACHE or ["127.0.0.1"]


def refresh_network_info() -> None:
    global LAN_IP_CACHE, LAN_IPS_CACHE, LAN_INFO_AT
    now = time.time()
    if LAN_IPS_CACHE and now - LAN_INFO_AT < 60:
        return
    ip = "127.0.0.1"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
    except OSError:
        pass
    found = []
    if ip and not ip.startswith("127."):
        found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            item = info[4][0]
            if item.startswith("127.") or item.startswith("169.254."):
                continue
            if item not in found:
                found.append(item)
    except OSError:
        pass
    LAN_IP_CACHE = ip
    LAN_IPS_CACHE = found or [ip]
    LAN_INFO_AT = now


def wifi_name() -> str:
    global WIFI_NAME_CACHE
    if WIFI_NAME_CACHE:
        return WIFI_NAME_CACHE
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-NetConnectionProfile | Select-Object -First 1).Name",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
        WIFI_NAME_CACHE = (result.stdout or "").strip()
        return WIFI_NAME_CACHE
    except Exception:
        return ""


def ssh_binary() -> str:
    found = shutil.which("ssh")
    if found:
        return found
    fallback = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
    return str(fallback) if fallback.exists() else ""


def hidden_startup() -> tuple[subprocess.STARTUPINFO | None, int]:
    if os.name != "nt":
        return None, 0
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo, 0x08000000


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def ensure_cloudflared() -> str:
    if CLOUDFLARED.exists() and CLOUDFLARED.stat().st_size > 1_000_000:
        return str(CLOUDFLARED)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    print("Скачиваю программу для интернет-ссылки (один раз)…", flush=True)
    last_error = ""
    for url in CLOUDFLARED_URLS:
        tmp = CLOUDFLARED.with_suffix(".exe.download")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "journal-app"})
            with urllib.request.urlopen(req, timeout=120) as response, tmp.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    out.write(chunk)
            if tmp.stat().st_size < 1_000_000:
                tmp.unlink(missing_ok=True)
                last_error = "файл слишком маленький"
                continue
            tmp.replace(CLOUDFLARED)
            return str(CLOUDFLARED)
        except Exception as exc:
            last_error = str(exc)
            tmp.unlink(missing_ok=True)
    raise RuntimeError(last_error or "не удалось скачать cloudflared")


def kill_lingering_tunnels() -> None:
    global TUNNEL_PROC
    if TUNNEL_PROC and TUNNEL_PROC.poll() is None:
        try:
            TUNNEL_PROC.terminate()
            TUNNEL_PROC.wait(timeout=4)
        except Exception:
            try:
                TUNNEL_PROC.kill()
            except Exception:
                pass
    TUNNEL_PROC = None
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/IM", "cloudflared.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


PINGGY_URL_RE = re.compile(r"https?://[A-Za-z0-9.-]*pinggy[A-Za-z0-9.-]*")
CLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def student_share_url(candidate: str = "") -> str:
    """Ссылка, которую ученик открывает. Не Pinggy и не Cloudflare-туннель."""
    configured = os.environ.get("JOURNAL_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    text = str(candidate or "").strip().rstrip("/")
    if text and not EPHEMERAL_SHARE_RE.search(text):
        host = (urlparse(text).hostname or "").replace("www.", "").lower()
        if host == "rusklasst.ru":
            return STUDENT_SITE_URL
    return STUDENT_SITE_URL


def should_start_tunnel() -> bool:
    if os.environ.get("JOURNAL_DISABLE_TUNNEL") == "1":
        return False
    if os.environ.get("JOURNAL_PUBLIC_URL", "").strip():
        return False
    if os.environ.get("INVOCATION_ID"):
        return False
    return True


def _announce_public_url(port: int) -> None:
    print("", flush=True)
    print("Ссылка для телефона и ученика (откроется из любой сети):", flush=True)
    print(PUBLIC_URL, flush=True)
    print("Пока эта ссылка работает, не выключайте компьютер и не закрывайте окно.", flush=True)
    ssid = wifi_name()
    wifi = f" «{ssid}»" if ssid else ""
    print(f"Если телефон в той же Wi-Fi{wifi}, запасной адрес:", flush=True)
    print(f"http://{lan_ip()}:{port}/", flush=True)
    print("На телефоне нужен http://, не https://", flush=True)
    print("", flush=True)


def _run_piped_tunnel(
    command: list[str],
    url_re: re.Pattern[str],
    port: int,
    log_path: Path,
    url_timeout: float | None = None,
) -> str:
    global PUBLIC_URL, TUNNEL_ERROR, TUNNEL_PROC
    startupinfo, flags = hidden_startup()
    log_file = log_path.open("a", encoding="utf-8")
    state = {"reason": "failed", "got_url": False}
    try:
        TUNNEL_PROC = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            creationflags=flags,
        )
    except Exception as exc:
        log_file.close()
        TUNNEL_ERROR = f"Не удалось запустить интернет-ссылку: {exc}"
        print(TUNNEL_ERROR, flush=True)
        return "failed"
    assert TUNNEL_PROC.stdout is not None

    def watchdog() -> None:
        if not url_timeout:
            return
        time.sleep(url_timeout)
        if not state["got_url"] and TUNNEL_PROC and TUNNEL_PROC.poll() is None:
            state["reason"] = "timeout"
            try:
                TUNNEL_PROC.terminate()
            except Exception:
                pass

    threading.Thread(target=watchdog, daemon=True).start()
    while TUNNEL_PROC.poll() is None:
        line = TUNNEL_PROC.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        clean = strip_ansi(line)
        try:
            log_file.write(clean)
            log_file.flush()
        except Exception:
            pass
        if "429" in clean or "1015" in clean or "Too Many Requests" in clean:
            state["reason"] = "rate-limit"
            TUNNEL_ERROR = "Бесплатная интернет-ссылка временно недоступна. С телефона откройте адрес с http:// в той же Wi‑Fi."
            try:
                TUNNEL_PROC.terminate()
            except Exception:
                pass
            break
        match = url_re.search(clean)
        if match:
            url = match.group(0).rstrip(".,);")
            if url.startswith("http://"):
                url = "https://" + url[len("http://") :]
            if url != PUBLIC_URL:
                PUBLIC_URL = url
                TUNNEL_ERROR = ""
                state["got_url"] = True
                state["reason"] = "ok"
                _announce_public_url(port)
    try:
        log_file.close()
    except Exception:
        pass
    PUBLIC_URL = ""
    if state["got_url"] and state["reason"] == "ok":
        return "ok"
    return state["reason"]


def start_tunnel(port: int) -> None:
    def worker() -> None:
        global PUBLIC_URL, TUNNEL_ERROR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / "tunnel.log"
        kill_lingering_tunnels()
        ssh = ssh_binary()
        while True:
            PUBLIC_URL = ""
            if ssh:
                TUNNEL_ERROR = "Готовлю ссылку для телефона…"
                pinggy_cmd = [
                    ssh,
                    "-p",
                    "443",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=NUL",
                    "-o",
                    "ServerAliveInterval=30",
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-T",
                    "-R",
                    f"0:127.0.0.1:{port}",
                    "free.pinggy.io",
                ]
                reason = _run_piped_tunnel(
                    pinggy_cmd, PINGGY_URL_RE, port, log_path, url_timeout=18
                )
                kill_lingering_tunnels()
                if reason == "ok":
                    TUNNEL_ERROR = "Интернет-ссылка обновится через несколько секунд. Скопируйте её заново."
                    print("Ссылка для телефона оборвалась, поднимаю новую…", flush=True)
                    time.sleep(4)
                    continue
            TUNNEL_ERROR = "Пробую запасную интернет-ссылку…"
            try:
                binary = ensure_cloudflared()
            except Exception as exc:
                TUNNEL_ERROR = (
                    f"Интернет-ссылка пока не готова ({exc}). "
                    f"С телефона откройте http://{lan_ip()}:{port}/ в той же Wi‑Fi, обязательно http, не https."
                )
                print(TUNNEL_ERROR, flush=True)
                time.sleep(20)
                continue
            cf_cmd = [
                binary,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{port}",
                "--no-autoupdate",
                "--protocol",
                "http2",
                "--edge-ip-version",
                "4",
            ]
            reason = _run_piped_tunnel(
                cf_cmd, CLOUDFLARE_URL_RE, port, log_path, url_timeout=25
            )
            kill_lingering_tunnels()
            if reason == "rate-limit":
                TUNNEL_ERROR = (
                    f"Бесплатные интернет-ссылки временно ограничены. "
                    f"С телефона откройте http://{lan_ip()}:{port}/ — только http, не https. "
                    "Если не открывается, запустите файл «разрешить-телефон.bat» и нажмите Да."
                )
                print(TUNNEL_ERROR, flush=True)
                time.sleep(1800)
                continue
            TUNNEL_ERROR = f"С телефона: http://{lan_ip()}:{port}/ (http, не https). Если не открывается — «разрешить-телефон.bat»."
            print(TUNNEL_ERROR, flush=True)
            time.sleep(15)

    threading.Thread(target=worker, daemon=True).start()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, format: str, *args) -> None:
        path = ""
        if args:
            path = str(args[0])
        if "/api/session" in path or "/api/table" in path:
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if ctype in ("text/html", "text/css", "text/javascript", "application/javascript"):
            return f"{ctype}; charset=utf-8"
        return ctype

    def _send_json(self, payload: dict, status: int = 200, cookie: str | None = None) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "replace")
        except Exception:
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
        except Exception:
            return

    def _cookie_header(self, token: str | None, max_age: int = SESSION_MAX_AGE) -> str:
        secure = "; Secure" if self._cookie_secure() else ""
        if not token:
            return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax{secure}; Max-Age=0"
        return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax{secure}; Max-Age={max_age}"

    def _cookie_secure(self) -> bool:
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        if proto == "https":
            return True
        return request_hostname(self) in PUBLIC_HOSTS

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _user(self) -> dict | None:
        session = get_session(self._token())
        if session:
            return session
        if allow_local_teacher(self):
            return {
                "role": "teacher",
                "login": "учитель",
                "name": "Учитель",
                "student_id": None,
                "local": True,
            }
        return None

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 2_000_000:
            self._send_json({"ok": False, "error": "Слишком большой запрос"}, 413)
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"ok": False, "error": "Некорректный JSON"}, 400)
            return None
        if not isinstance(data, dict):
            self._send_json({"ok": False, "error": "Ожидается объект"}, 400)
            return None
        return data

    def _session_payload(self, user: dict | None) -> dict:
        port = self.server.server_address[1]
        return {
            "user": None
            if not user
            else {
                "role": user["role"],
                "login": user["login"],
                "name": user["name"],
                "studentId": user.get("student_id"),
            },
            "localTeacher": bool(user and user.get("local")),
            "publicUrl": student_share_url(PUBLIC_URL),
            "localUrl": f"http://127.0.0.1:{port}/",
            "lanUrl": f"http://{lan_ip()}:{port}/",
            "lanUrls": [f"http://{ip}:{port}/" for ip in lan_ips()],
            "wifiName": wifi_name(),
            "tunnelError": TUNNEL_ERROR,
            "pdfImport": True,
        }

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/session":
            self._send_json(self._session_payload(self._user()))
            return
        if path == "/api/students":
            try:
                user = self._user()
                if not user:
                    self._send_json({"ok": False, "error": "Нужно войти"}, 401)
                    return
                with DATA_LOCK:
                    data = load_data()
                if user["role"] == "teacher":
                    self._send_json(journal.public_students_payload(data.get("students")))
                    return
                student = find_student(data, user.get("student_id", ""))
                payload = public_student(student)
                self._send_json({"students": [payload] if payload else []})
            except Exception:
                self._send_json({"ok": False, "error": "Не получилось открыть журнал"}, 500)
            return
        if path == "/api/banks":
            if not self._user():
                self._send_json({"ok": False, "error": "Нужно войти"}, 401)
                return
            self._send_json({"banks": journal.list_banks()})
            return
        if path == "/api/practice":
            user = self._user()
            if not user:
                self._send_json({"ok": False, "error": "Нужно войти"}, 401)
                return
            self._practice(user)
            return
        if path == "/api/file":
            self._serve_upload()
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/login":
            self._login()
            return
        if path == "/api/logout":
            drop_session(self._token())
            self._send_json({"ok": True}, cookie=self._cookie_header(None))
            return
        user = self._user()
        if not user:
            self._send_json({"ok": False, "error": "Нужно войти"}, 401)
            return
        if path == "/api/students":
            self._create_student(user)
            return
        if path == "/api/students/delete":
            self._delete_student(user)
            return
        if path == "/api/students/password":
            self._set_student_password(user)
            return
        if path == "/api/teacher/password":
            self._set_teacher_password(user)
            return
        if path == "/api/table":
            self._save_table(user)
            return
        if path == "/api/table/copy":
            self._copy_table(user)
            return
        if path == "/api/schedule":
            self._save_schedule(user)
            return
        if path == "/api/progress":
            self._save_progress(user)
            return
        if path == "/api/bank-key":
            self._save_bank_key(user)
            return
        if path == "/api/upload":
            self._upload_material(user)
            return
        if path == "/api/import-pdf":
            self._import_pdf(user)
            return
        if path == "/api/file/delete":
            self._delete_material(user)
            return
        if path == "/api/banks/delete":
            self._delete_bank(user)
            return
        self._drain_body()
        self.send_error(404)

    def _drain_body(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return
        leftover = min(max(length, 0), MAX_UPLOAD_BYTES + 1)
        while leftover > 0:
            chunk = self.rfile.read(min(65536, leftover))
            if not chunk:
                break
            leftover -= len(chunk)

    def _login(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        ip = request_client_ip(self)
        if too_many_logins(ip):
            self._send_json({"ok": False, "error": "Слишком много попыток. Подождите несколько минут."}, 429)
            return
        login = str(payload.get("login") or "").strip()
        password = str(payload.get("password") or "")
        if not login or not password:
            self._send_json({"ok": False, "error": "Введите логин и пароль"}, 400)
            return

        auth = load_auth()
        if login.casefold() == auth["teacher_login"].casefold() and check_password(
            password, auth["teacher_salt"], auth["teacher_password_hash"]
        ):
            if not allow_local_teacher(self) and auth.get("teacher_password_is_initial"):
                mark_login_fail(ip)
                self._send_json({"ok": False, "error": "Неверный логин или пароль"}, 401)
                return
            token = new_session(
                {
                    "role": "teacher",
                    "login": auth["teacher_login"],
                    "name": "Учитель",
                    "student_id": None,
                }
            )
            self._send_json({"ok": True, **self._session_payload(get_session(token))}, cookie=self._cookie_header(token))
            return

        with DATA_LOCK:
            data = load_data()
            student = next(
                (
                    item
                    for item in data["students"]
                    if str(item.get("login", "")).casefold() == login.casefold()
                ),
                None,
            )
            if student and check_password(
                password, student.get("password_salt", ""), student.get("password_hash", "")
            ):
                token = new_session(
                    {
                        "role": "student",
                        "login": student.get("login"),
                        "name": student.get("name") or student.get("login"),
                        "student_id": student.get("id"),
                    }
                )
                self._send_json(
                    {"ok": True, **self._session_payload(get_session(token))},
                    cookie=self._cookie_header(token),
                )
                return

        mark_login_fail(ip)
        self._send_json({"ok": False, "error": "Неверный логин или пароль"}, 401)

    def _create_student(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Только учитель может добавлять учеников"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        name = str(payload.get("name") or "").strip()
        login = str(payload.get("login") or "").strip() or slug_login(name)
        password = str(payload.get("password") or "").strip() or generate_password()
        template = "twice" if payload.get("template") == "twice" else "once"
        if not name:
            self._send_json({"ok": False, "error": "Нужно имя ученика"}, 400)
            return
        grade = journal.clean_grade(payload.get("grade"))
        if not grade:
            self._send_json({"ok": False, "error": "Укажите класс ученика"}, 400)
            return
        login = login.replace(" ", "")
        start = journal.parse_iso_date(str(payload.get("startDate") or ""))
        slots = journal.clean_slots(payload.get("slots"), template)
        requested_end, end_error = journal.parse_end_date_value(payload.get("endDate"))
        if end_error:
            self._send_json({"ok": False, "error": end_error}, 400)
            return
        end = None
        if start and slots:
            end, span_error = journal.resolve_schedule_end(start, slots, requested_end)
            if span_error:
                self._send_json({"ok": False, "error": span_error}, 400)
                return
        with DATA_LOCK:
            base = login
            suffix = 2
            while login_taken(login):
                login = f"{base}{suffix}"
                suffix += 1
            salt, digest = hash_password(password)
            student = {
                "id": str(uuid.uuid4()),
                "name": name,
                "grade": grade,
                "login": login,
                "template": template,
                "rows": [journal.empty_row() for _ in range(5)],
                "progress": {},
                "password_salt": salt,
                "password_hash": digest,
                "password_is_initial": False,
            }
            if start and slots:
                journal.apply_schedule(student, start, slots, template, end)
            data = load_data()
            data["students"].append(student)
            save_data(data)
        self._send_json(
            {
                "ok": True,
                "student": public_student(student),
                "login": login,
                "password": password,
            }
        )

    def _delete_student(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Только учитель может удалять учеников"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        student_id = str(payload.get("id") or "")
        with DATA_LOCK:
            data = load_data()
            data["students"] = [item for item in data["students"] if item.get("id") != student_id]
            save_data(data)
        self._send_json({"ok": True})

    def _set_student_password(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Только учитель может менять пароль ученика"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        student_id = str(payload.get("id") or "")
        password = str(payload.get("password") or "").strip()
        if payload.get("reset") or not password:
            password = generate_password()
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            salt, digest = hash_password(password)
            student["password_salt"] = salt
            student["password_hash"] = digest
            student["password_is_initial"] = False
            save_data(data)
            login = str(student.get("login") or "")
        self._send_json({"ok": True, "login": login, "password": password})

    def _set_teacher_password(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Недостаточно прав"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        password = str(payload.get("password") or "").strip()
        if len(password) < 4:
            self._send_json({"ok": False, "error": "Пароль не короче 4 символов"}, 400)
            return
        auth = load_auth()
        salt, digest = hash_password(password)
        auth["teacher_salt"] = salt
        auth["teacher_password_hash"] = digest
        auth["teacher_password_is_initial"] = False
        save_auth(auth)
        self._send_json({"ok": True})

    def _save_table(self, user: dict) -> None:
        payload = self._read_json()
        if payload is None:
            return
        student_id = str(payload.get("id") or "")
        if user["role"] == "student":
            student_id = user.get("student_id") or ""
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            end = journal.parse_iso_date(str((student.get("schedule") or {}).get("endDate") or ""))
            new_rows = journal.clean_rows(
                payload.get("rows"),
                keep_from_old=student.get("rows") if isinstance(student.get("rows"), list) else [],
                student_locked=user["role"] == "student",
                end=end,
            )
            if user["role"] == "student":
                old_rows = student.get("rows") if isinstance(student.get("rows"), list) else []
                for index, row in enumerate(new_rows):
                    if index < len(old_rows) and isinstance(old_rows[index], dict):
                        row["comment"] = str(old_rows[index].get("comment", "") or "")
            student["rows"] = new_rows
            if user["role"] == "teacher" and payload.get("template") in ("once", "twice"):
                student["template"] = payload["template"]
            save_data(data)
            saved = public_student(student)
        self._send_json({"ok": True, "student": saved})

    def _copy_table(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Копировать таблицы может только учитель"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        source_id = str(payload.get("sourceId") or "")
        target_id = str(payload.get("targetId") or "")
        if not source_id or not target_id or source_id == target_id:
            self._send_json({"ok": False, "error": "Выберите двух разных учеников"}, 400)
            return
        with DATA_LOCK:
            data = load_data()
            source = find_student(data, source_id)
            target = find_student(data, target_id)
            if not source or not target:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            replaced_uploads = row_upload_ids(target.get("rows"))
            journal.copy_student_table(source, target)
            save_data(data)
            for file_id in replaced_uploads:
                if not upload_is_referenced(data, file_id):
                    (UPLOADS_DIR / file_id).unlink(missing_ok=True)
            saved = public_student(target)
        self._send_json(
            {
                "ok": True,
                "student": saved,
                "sourceName": str(source.get("name") or ""),
            }
        )

    def _save_schedule(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Расписание задаёт учитель"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        student_id = str(payload.get("id") or "")
        start = journal.parse_iso_date(str(payload.get("startDate") or ""))
        template = "twice" if payload.get("template") == "twice" else "once"
        slots = journal.clean_slots(payload.get("slots"), template)
        requested_end, end_error = journal.parse_end_date_value(payload.get("endDate"))
        if end_error:
            self._send_json({"ok": False, "error": end_error}, 400)
            return
        if not start:
            self._send_json({"ok": False, "error": "Укажите дату первого занятия"}, 400)
            return
        if not slots:
            self._send_json({"ok": False, "error": "Укажите день недели и время"}, 400)
            return
        if template == "twice" and len(slots) < 2:
            self._send_json({"ok": False, "error": "Для двух занятий в неделю нужны два разных дня"}, 400)
            return
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            fallback_end = journal.parse_iso_date(str((student.get("schedule") or {}).get("endDate") or ""))
            end, span_error = journal.resolve_schedule_end(start, slots, requested_end, fallback_end)
            if span_error:
                self._send_json({"ok": False, "error": span_error}, 400)
                return
            student["template"] = template
            name = str(payload.get("name") or "").strip()
            if name:
                student["name"] = name
            grade = journal.clean_grade(payload.get("grade"))
            if grade:
                student["grade"] = grade
            student["schedule"] = {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "slots": slots,
            }
            if payload.get("regenerate", True):
                journal.apply_schedule(student, start, slots, template, end)
            save_data(data)
            saved = public_student(student)
        self._send_json({"ok": True, "student": saved})

    def _practice(self, user: dict) -> None:
        query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        bank_id = query.get("bankId") or "ege-10"
        student_id = query.get("studentId") or ""
        if user["role"] == "student":
            student_id = user.get("student_id") or ""
        bank = journal.load_bank(bank_id)
        if not bank:
            self._send_json({"ok": False, "error": "Банк заданий не найден"}, 404)
            return
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
        if not student:
            self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
            return
        role = user["role"]
        if role == "teacher" and query.get("asStudent") == "1":
            role = "student"
        self._send_json(journal.public_practice(bank, student, role))

    def _save_progress(self, user: dict) -> None:
        payload = self._read_json()
        if payload is None:
            return
        student_id = str(payload.get("studentId") or "")
        if user["role"] == "student":
            student_id = user.get("student_id") or ""
        bank_id = str(payload.get("bankId") or "")
        try:
            number = int(payload.get("n"))
        except (TypeError, ValueError):
            self._send_json({"ok": False, "error": "Некорректный номер задания"}, 400)
            return
        if not journal.load_bank(bank_id):
            self._send_json({"ok": False, "error": "Банк заданий не найден"}, 404)
            return
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            if user["role"] == "student" and journal.has_task_answer(student, bank_id, number):
                self._send_json({"ok": False, "error": "Ответ уже сохранён. Изменить его нельзя."}, 409)
                return
            stats = journal.set_task_answer(student, bank_id, number, str(payload.get("answer") or ""))
            save_data(data)
        self._send_json({"ok": True, "stats": stats, "statsColor": journal.progress_color(stats["percent"])})

    def _save_bank_key(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Ключ ответов задаёт учитель"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        try:
            number = int(payload.get("n"))
        except (TypeError, ValueError):
            self._send_json({"ok": False, "error": "Некорректный номер задания"}, 400)
            return
        if not journal.set_bank_key(str(payload.get("bankId") or ""), number, str(payload.get("answer") or "")):
            self._send_json({"ok": False, "error": "Не удалось сохранить ключ"}, 400)
            return
        self._send_json({"ok": True})

    def _serve_upload(self) -> None:
        query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        file_id = safe_upload_id(query.get("id") or "")
        if not file_id:
            self._send_json({"ok": False, "error": "Файл не найден"}, 404)
            return
        path = UPLOADS_DIR / file_id
        if not path.is_file():
            self._send_json({"ok": False, "error": "Файл не найден"}, 404)
            return
        download_name = Path(unquote(query.get("name") or file_id)).name or file_id
        download_name = re.sub(r'[\r\n"]+', "", download_name)[:180] or file_id
        data = path.read_bytes()
        ctype = mimetypes.guess_type(file_id)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f"inline; filename*=UTF-8''{quote(download_name)}",
        )
        self.send_header("Cache-Control", "private, max-age=120")
        self.end_headers()
        self.wfile.write(data)

    def _import_pdf(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "PDF разбирает учитель"}, 403)
            return
        content_type = self.headers.get("Content-Type") or ""
        pdf_bytes = b""
        source_name = "zadaniya.pdf"
        source_key = ""
        student_id = ""
        row_index = -1
        if "multipart/form-data" in content_type:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                self._send_json({"ok": False, "error": "Файл слишком большой (до 20 МБ)"}, 400)
                return
            parsed = parse_multipart(self.headers, self.rfile.read(length))
            fields = parsed.get("fields") or {}
            uploaded = parsed.get("file")
            student_id = str(fields.get("studentId") or "")
            try:
                row_index = int(fields.get("row"))
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": "Некорректная строка"}, 400)
                return
            if not uploaded or not uploaded.get("data"):
                self._send_json({"ok": False, "error": "Выберите PDF"}, 400)
                return
            pdf_bytes = uploaded["data"]
            source_name = Path(uploaded.get("filename") or "zadaniya.pdf").name
            source_key = f"upload:{source_name}"
        else:
            payload = self._read_json()
            if payload is None:
                return
            student_id = str(payload.get("studentId") or "")
            try:
                row_index = int(payload.get("row"))
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": "Некорректная строка"}, 400)
                return
            url = str(payload.get("url") or "").strip()
            from_field = str(payload.get("fromField") or "")
            if url:
                try:
                    pdf_bytes, source_name = pdf_import.download_pdf(url)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                    return
                source_key = pdf_import.canonical_source_url(url)
            elif from_field == "practice":
                with DATA_LOCK:
                    data = load_data()
                    student = find_student(data, student_id)
                    if not student:
                        self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                        return
                    rows = student.get("rows") if isinstance(student.get("rows"), list) else []
                    if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
                        self._send_json({"ok": False, "error": "Строка не найдена"}, 400)
                        return
                    file_id = safe_upload_id(str(rows[row_index].get(f"{from_field}FileId") or ""))
                    file_name = str(rows[row_index].get(f"{from_field}FileName") or file_id)
                if not file_id or Path(file_id).suffix.lower() != ".pdf":
                    self._send_json({"ok": False, "error": "В этой строке нет PDF"}, 400)
                    return
                path = UPLOADS_DIR / file_id
                if not path.is_file():
                    self._send_json({"ok": False, "error": "Файл не найден"}, 404)
                    return
                pdf_bytes = path.read_bytes()
                source_name = file_name or file_id
                source_key = f"file:{file_id}"
            else:
                self._send_json({"ok": False, "error": "Нужен PDF или ссылка на него"}, 400)
                return
        try:
            parsed_bank = pdf_import.import_pdf_bytes(
                pdf_bytes, source_name, journal.pdf_bank_id(pdf_bytes)
            )
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        except Exception:
            self._send_json({"ok": False, "error": "Не получилось разобрать PDF."}, 400)
            return
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            try:
                bank = attach_pdf_bank(
                    data, student, row_index, b"", source_name, source_key, parsed=parsed_bank
                )
                save_data(data)
                saved = public_student(student)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            except Exception:
                self._send_json({"ok": False, "error": "Не получилось сохранить задания из PDF."}, 400)
                return
        self._send_json(
            {
                "ok": True,
                "student": saved,
                "bankId": bank["id"],
                "total": len(bank.get("tasks") or []),
            }
        )

    def _upload_material(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Материал прикрепляет учитель"}, 403)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._send_json({"ok": False, "error": "Файл слишком большой (до 20 МБ)"}, 400)
            return
        parsed = parse_multipart(self.headers, self.rfile.read(length))
        fields = parsed.get("fields") or {}
        uploaded = parsed.get("file")
        if not uploaded or not uploaded.get("data"):
            self._send_json({"ok": False, "error": "Выберите файл"}, 400)
            return
        field = str(fields.get("field") or "theory")
        if field not in ("theory", "homework", "practice"):
            self._send_json({"ok": False, "error": "Некорректное поле"}, 400)
            return
        student_id = str(fields.get("studentId") or "")
        try:
            row_index = int(fields.get("row"))
        except (TypeError, ValueError):
            self._send_json({"ok": False, "error": "Некорректная строка"}, 400)
            return
        original = Path(uploaded["filename"] or "material").name
        suffix = Path(original).suffix.lower()
        if suffix not in UPLOAD_EXTENSIONS:
            self._send_json({"ok": False, "error": "Можно прикрепить PDF, Word, презентацию или картинку"}, 400)
            return
        if field == "practice" and suffix != ".pdf":
            self._send_json({"ok": False, "error": "В практику загрузите PDF с заданиями"}, 400)
            return
        stored = f"{uuid.uuid4().hex}{suffix}"
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOADS_DIR / stored
        dest.write_bytes(uploaded["data"])
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                dest.unlink(missing_ok=True)
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            rows = student.get("rows") if isinstance(student.get("rows"), list) else []
            if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
                dest.unlink(missing_ok=True)
                self._send_json({"ok": False, "error": "Строка не найдена"}, 400)
                return
            try:
                old_id = journal.attach_row_file(rows[row_index], field, stored, original)
            except ValueError as exc:
                dest.unlink(missing_ok=True)
                self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            old_id = safe_upload_id(str(old_id or ""))
            save_data(data)
            if old_id and not upload_is_referenced(data, old_id):
                (UPLOADS_DIR / old_id).unlink(missing_ok=True)
            saved = public_student(student)
        payload = {"ok": True, "student": saved}
        if field == "practice" and suffix == ".pdf":
            payload["needsImport"] = True
        self._send_json(payload)

    def _delete_material(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Файл удаляет учитель"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        field = str(payload.get("field") or "")
        if field not in ("theory", "homework", "practice"):
            self._send_json({"ok": False, "error": "Некорректное поле"}, 400)
            return
        student_id = str(payload.get("studentId") or "")
        try:
            row_index = int(payload.get("row"))
        except (TypeError, ValueError):
            self._send_json({"ok": False, "error": "Некорректная строка"}, 400)
            return
        with DATA_LOCK:
            data = load_data()
            student = find_student(data, student_id)
            if not student:
                self._send_json({"ok": False, "error": "Ученик не найден"}, 404)
                return
            rows = student.get("rows") if isinstance(student.get("rows"), list) else []
            if row_index < 0 or row_index >= len(rows) or not isinstance(rows[row_index], dict):
                self._send_json({"ok": False, "error": "Строка не найдена"}, 400)
                return
            old_id = safe_upload_id(
                str(journal.detach_row_file(rows[row_index], field, payload.get("fileId")) or "")
            )
            save_data(data)
            if old_id and not upload_is_referenced(data, old_id):
                (UPLOADS_DIR / old_id).unlink(missing_ok=True)
            saved = public_student(student)
        self._send_json({"ok": True, "student": saved})

    def _delete_bank(self, user: dict) -> None:
        if user["role"] != "teacher":
            self._send_json({"ok": False, "error": "Набор удаляет учитель"}, 403)
            return
        payload = self._read_json()
        if payload is None:
            return
        bank_id = str(payload.get("id") or "")
        with DATA_LOCK:
            data = load_data()
            error = journal.purge_bank(data, bank_id)
            if error:
                self._send_json({"ok": False, "error": error}, 400)
                return
            save_data(data)
            students = journal.public_students_payload(data.get("students")).get("students") or []
        self._send_json({"ok": True, "banks": journal.list_banks(), "students": students})


def ensure_lan_firewall(port: int) -> None:
    if os.name != "nt":
        return
    name = "JournalLocalPhone"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    added = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={str(port)}",
            "profile=any",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    python_exe = sys.executable
    if python_exe:
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                "name=JournalPython",
                "dir=in",
                "action=allow",
                f"program={python_exe}",
                "profile=any",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if added.returncode == 0:
        print("Брандмауэр: доступ с телефона в той же Wi-Fi разрешён.", flush=True)
    else:
        print(
            "Брандмауэр не открылся сам. Один раз запустите «разрешить-телефон.bat» и нажмите Да.",
            flush=True,
        )


def find_port(start: int = START_PORT, attempts: int = 12) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("Не удалось найти свободный порт")


class JournalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


def main() -> None:
    global TUNNEL_PROC, PUBLIC_URL, TUNNEL_ERROR
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_auth()
    migrate_students()
    load_sessions()

    port = find_port()
    ensure_lan_firewall(port)
    httpd = JournalServer((HOST, port), Handler)
    local_url = f"http://127.0.0.1:{port}/"
    print("Журнал занятий открывается в браузере.", flush=True)
    print(local_url, flush=True)
    print("", flush=True)
    ssid = wifi_name()
    wifi = f" «{ssid}»" if ssid else ""
    print(f"Сайт для ученика: {student_share_url()}", flush=True)
    if should_start_tunnel():
        print(f"Готовлю ссылку для телефона. Запасной адрес в Wi-Fi{wifi}:", flush=True)
        print(f"http://{lan_ip()}:{port}/", flush=True)
        print("На телефоне вводите http://, не https://", flush=True)
        print("Если Wi-Fi не открывается — файл «разрешить-телефон.bat», кнопка Да.", flush=True)
        start_tunnel(port)
    else:
        PUBLIC_URL = student_share_url()
        TUNNEL_ERROR = ""
    print("Чтобы закрыть программу, закройте это окно.", flush=True)
    threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.", flush=True)
    finally:
        httpd.server_close()
        kill_lingering_tunnels()


if __name__ == "__main__":
    main()
