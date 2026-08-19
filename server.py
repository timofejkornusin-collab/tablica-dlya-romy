#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал занятий: таблицы учеников и ссылка для телефона."""

from __future__ import annotations

import hashlib
import hmac
import json
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
from urllib.parse import parse_qs, urlparse

import journal

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA_DIR = ROOT / "data"
TOOLS_DIR = ROOT / "tools"
DATA_FILE = DATA_DIR / "students.json"
AUTH_FILE = DATA_DIR / "auth.json"
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
WIFI_NAME_CACHE = ""
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


def slug_login(name: str) -> str:
    raw = []
    for char in (name or "").strip().lower():
        if char in RU_TO_LAT:
            raw.append(RU_TO_LAT[char])
        elif char.isalnum():
            raw.append(char)
    login = "".join(raw) or "uchenik"
    return login[:40]


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


def too_many_logins(ip: str) -> bool:
    now = time.time()
    with SESSION_LOCK:
        hits = [stamp for stamp in LOGIN_HITS.get(ip, []) if now - stamp < 600]
        LOGIN_HITS[ip] = hits
        return len(hits) >= 12


def mark_login_fail(ip: str) -> None:
    with SESSION_LOCK:
        LOGIN_HITS.setdefault(ip, []).append(time.time())


def new_session(payload: dict) -> str:
    token = secrets.token_urlsafe(24)
    with SESSION_LOCK:
        SESSIONS[token] = payload
    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    with SESSION_LOCK:
        return SESSIONS.get(token)


def drop_session(token: str | None) -> None:
    if not token:
        return
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


def lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def lan_ips() -> list[str]:
    found: list[str] = []
    primary = lan_ip()
    if primary and not primary.startswith("127."):
        found.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found or ["127.0.0.1"]


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
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if ctype in ("text/html", "text/css", "text/javascript", "application/javascript"):
            return f"{ctype}; charset=utf-8"
        return ctype

    def _send_json(self, payload: dict, status: int = 200, cookie: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _cookie_header(self, token: str | None, max_age: int = 60 * 60 * 14) -> str:
        if not token:
            return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _user(self) -> dict:
        return get_session(self._token()) or {
            "role": "teacher",
            "login": "учитель",
            "name": "Учитель",
            "student_id": None,
        }

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
            "publicUrl": PUBLIC_URL,
            "localUrl": f"http://127.0.0.1:{port}/",
            "lanUrl": f"http://{lan_ip()}:{port}/",
            "lanUrls": [f"http://{ip}:{port}/" for ip in lan_ips()],
            "wifiName": wifi_name(),
            "tunnelError": TUNNEL_ERROR,
        }

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/session":
            self._send_json(self._session_payload(self._user()))
            return
        if path == "/api/students":
            user = self._user()
            if not user:
                self._send_json({"ok": False, "error": "Нужно войти"}, 401)
                return
            with DATA_LOCK:
                data = load_data()
            if user["role"] == "teacher":
                self._send_json({"students": [public_student(item) for item in data["students"] if public_student(item)]})
                return
            student = find_student(data, user.get("student_id", ""))
            payload = public_student(student)
            self._send_json({"students": [payload] if payload else []})
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
        if path == "/api/schedule":
            self._save_schedule(user)
            return
        if path == "/api/progress":
            self._save_progress(user)
            return
        if path == "/api/bank-key":
            self._save_bank_key(user)
            return
        self.send_error(404)

    def _login(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        ip = self.client_address[0]
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
        password = str(payload.get("password") or "").strip() or secrets.token_hex(8)
        template = "twice" if payload.get("template") == "twice" else "once"
        if not name:
            self._send_json({"ok": False, "error": "Нужно имя ученика"}, 400)
            return
        login = login.replace(" ", "")
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
                "login": login,
                "template": template,
                "rows": [journal.empty_row() for _ in range(5)],
                "progress": {},
                "password_salt": salt,
                "password_hash": digest,
                "password_is_initial": False,
            }
            start = journal.parse_iso_date(str(payload.get("startDate") or ""))
            slots = journal.clean_slots(payload.get("slots"), template)
            if start and slots:
                journal.apply_schedule(student, start, slots, template)
            data = load_data()
            data["students"].append(student)
            save_data(data)
        self._send_json({"ok": True, "student": public_student(student)})

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
        if not password:
            self._send_json({"ok": False, "error": "Введите новый пароль"}, 400)
            return
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
        self._send_json({"ok": True})

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
            new_rows = journal.clean_rows(
                payload.get("rows"),
                keep_from_old=student.get("rows") if isinstance(student.get("rows"), list) else [],
                student_locked=user["role"] == "student",
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
            student["template"] = template
            student["schedule"] = {
                "startDate": start.isoformat(),
                "slots": slots,
            }
            if payload.get("regenerate", True):
                journal.apply_schedule(student, start, slots, template)
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
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("Не удалось найти свободный порт")


def main() -> None:
    global TUNNEL_PROC
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_auth()
    migrate_students()

    port = find_port()
    ensure_lan_firewall(port)
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    local_url = f"http://127.0.0.1:{port}/"
    print("Журнал занятий открывается в браузере.", flush=True)
    print(local_url, flush=True)
    print("", flush=True)
    ssid = wifi_name()
    wifi = f" «{ssid}»" if ssid else ""
    print(f"Готовлю ссылку для телефона. Запасной адрес в Wi-Fi{wifi}:", flush=True)
    print(f"http://{lan_ip()}:{port}/", flush=True)
    print("На телефоне вводите http://, не https://", flush=True)
    print("Если Wi-Fi не открывается — файл «разрешить-телефон.bat», кнопка Да.", flush=True)
    start_tunnel(port)
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
