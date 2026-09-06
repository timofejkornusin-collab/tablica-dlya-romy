# -*- coding: utf-8 -*-
"""Разобрать PDF с заданиями в банк практики журнала."""

from __future__ import annotations

import io
import ipaddress
import re
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

EGE_PROMPT = (
    "Укажите варианты ответов, в которых во всех словах одного ряда "
    "пропущена одна и та же буква. Запишите номера ответов."
)

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60
TASK_VERBS = (
    "Отредактируйте",
    "тредактируйте",
    "Сопоставьте",
    "опоставьте",
    "Прочитайте",
    "рочитайте",
    "Определите",
    "пределите",
    "Расставьте",
    "асставьте",
    "Установите",
    "становите",
    "Исправьте",
    "справьте",
    "Выпишите",
    "ыпишите",
    "Укажите",
    "кажите",
    "Выберите",
    "ыберите",
    "Найдите",
    "айдите",
    "Вставьте",
    "ставьте",
    "Запишите",
    "апишите",
    "Замените",
    "амените",
    "В одном",
    "одном",
    "Укажи",
    "кажи",
    "Выбери",
    "ыбери",
    "Прочитай",
    "рочитай",
)
TASK_START = re.compile(
    r"(?:^|(?<=[\s.]))(?:№\s*)?(\d{1,3})(?:\.\s*|\s+)(?=(?:%s))"
    % "|".join(sorted((re.escape(verb) for verb in TASK_VERBS), key=len, reverse=True)),
    re.M,
)
LOOSE_START = re.compile(r"(?m)^(?:№\s*)?(\d{1,3})[.)]\s+(?=[А-ЯЁA-Z])")
OPTION_BLOCK = re.compile(r"(?ms)^\s*([1-5])[.)]\s*(.*?)(?=^\s*[1-5][.)]\s*|\Z)")
ANSWER_LINE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])Ответ\s*:\s*(?!_{2,}|[—–\-.]{3,})([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9,\s-]{0,48})",
    re.I,
)
BLANK_ANSWER = re.compile(r"Ответ\s*:?\s*[_\-–—.]{3,}\.?", re.I)
EGE_BOILERPLATE = re.compile(
    r"варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква\.\s*"
    r"Запишите номера ответов\.\s*Ответ:\s*_+\.?\s*",
    re.I,
)
KEY_HEADING = re.compile(
    r"^(?:ключи ответов|ключ ответов|ответы к заданиям)\b.*$|^ответы\s*:?\s*$",
    re.I | re.M,
)
CAPS_WORD = re.compile(r"(?<![А-ЯЁа-яёA-Za-z])[А-ЯЁ]{3,}(?![А-ЯЁа-яёA-Za-z])")
TRAILING_TASK_NUM = re.compile(r"(?:\s+\d{1,3}\.?|\s*\d{1,3}\.)\s*$")
OPTION_LIST_START = re.compile(r"(?:(?<=^)|(?<=[\s.]))1[.)][ \t]*\S")
INLINE_OPTION = re.compile(
    r"(?:(?<=^)|(?<=[\s.]))([1-5])[.)][ \t]+(\S.*?)(?=(?:[\s.]+)[1-5][.)][ \t]+|\s*\Z)",
    re.S,
)
INSTRUCTION_END = re.compile(
    r"(?is)("
    r"Запишите номера этих предложений|"
    r"Запишите номера ответов|"
    r"запишите слово правильно|"
    r"Запишите это слово(?!\s*,)|"
    r"Выпишите это слово(?!\s*,)|"
    r"смысл высказывания|"
    r"нормы современного русского литературного языка(?!\s+и\s+сохраняя)|"
    r"на месте которой.{0,48}пишется(?:\s+одна\s+буква\s+Н|\s+НН|\s+Н)|"
    r"на месте которой.{0,80}запятая(?:\(-ые\))?"
    r")\.?"
)
WRITING_TARGET = r"(?:одна\s+буква\s+Н|НН|Н)"
SENTENCE_START = (
    r"(?!(?:Укажите|Запишите|Найдите|Выберите|Отредактируйте|Исправьте))"
    r"(?:[«\"“„]|[-—–]|[А-ЯЁ])"
)
PROMPT_SENTENCE_TAIL = (
    r"(?:смысл высказывания|литературного языка|"
    r"Запишите это слово|Выпишите это слово|запишите слово правильно|"
    r"подобранное слово|"
    r"пишется\s+" + WRITING_TARGET + r"|"
    r"запятая\(-ые\))"
)
WORD_HINTS = (
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
NUMBER_HINTS = (
    "запишите номера",
    "номера ответов",
    "номера этих",
    "цифру",
    "цифры",
    "цифр",
)


def extract_pdf_text(data: bytes) -> str:
    if not data.startswith(b"%PDF"):
        raise ValueError("Это не PDF-файл")
    text = _extract_pymupdf(data) or _extract_pypdf(data)
    text = _clean_extracted(text)
    if len(text.strip()) < 40:
        raise ValueError("В PDF почти нет текста. Скан-картинку программа пока не читает.")
    return text


def import_pdf_bytes(data: bytes, source_name: str, bank_id: str) -> dict:
    try:
        return build_bank(extract_pdf_text(data), source_name, bank_id)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Не получилось разобрать PDF. Нужен текстовый файл с нумерацией заданий.") from exc


def _extract_pymupdf(data: bytes) -> str:
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            return ""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return ""
    parts = []
    try:
        for index, page in enumerate(doc):
            if index >= MAX_PDF_PAGES:
                break
            parts.append(page.get_text("text") or "")
    finally:
        doc.close()
    return "\n".join(parts)


def _extract_pypdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    parts = []
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            break
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def _clean_extracted(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s*—\s*\d+\s+of\s+\d+\s*—", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(
        r"(Ответ\s*:?\s*[_\-–—.]{3,}\.?)\s*(?=[1-5][.)]|\(\d+\)[А-ЯЁA-Z«\"])",
        r"\1\n",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"((?:Запишите номера ответов|Запишите номера этих предложений|запишите слово правильно|Запишите это слово)\.)\s*(?=[1-5][.)]|\(\d+\)[А-ЯЁA-Z«\"])",
        r"\1\n\n",
        text,
        flags=re.I,
    )
    text = re.sub(
        rf"(пишется(?:\s+одна\s+буква\s+Н|\s+НН|\s+Н)\.)\s*(?={SENTENCE_START})",
        r"\1\n\n",
        text,
    )
    text = re.sub(
        rf"(запятая\(-ые\)\.)\s*(?={SENTENCE_START})",
        r"\1\n\n",
        text,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_tasks(text: str) -> list[dict]:
    tasks = [_make_task(number, body) for number, body in _split_tasks(text)]
    tasks = [item for item in tasks if item]
    if len(tasks) < 2:
        raise ValueError("Не удалось найти номера заданий в PDF. Нужен текстовый файл с нумерацией 1. 2. 3.")
    _apply_answer_section(text, tasks)
    return tasks


def _split_tasks(text: str) -> list[tuple[int, str]]:
    found = _chunks_from_matches(text, list(TASK_START.finditer(text)))
    if found:
        return found
    loose = []
    for number, body in _chunks_from_matches(text, list(LOOSE_START.finditer(text))):
        first = body.split("\n", 1)[0]
        if number <= 5 and ("…" in first or first.count(",") >= 2):
            continue
        loose.append((number, body))
    return _unique_tasks(loose)


def _chunks_from_matches(text: str, matches: list[re.Match[str]]) -> list[tuple[int, str]]:
    result = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if len(body) < 8:
            continue
        result.append((int(match.group(1)), body))
    return _unique_tasks(result)


def _unique_tasks(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    unique = []
    seen = set()
    for number, body in items:
        if number in seen:
            continue
        seen.add(number)
        unique.append((number, body))
    return unique


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def _make_task(number: int, body: str) -> dict | None:
    answer = _take_inline_answer(body)
    options = _options_1_to_5(body)
    kind = ""
    if not options:
        phrases = _phrase_options(body)
        if phrases:
            options = phrases
            kind = "phrases"
    prompt = _task_prompt(body, options)
    if not prompt and not any(options):
        return None
    if not kind and _looks_word_prompt(prompt) and not any(options):
        kind = "word"
    task = {"n": number, "prompt": prompt, "options": options, "answer": answer}
    if kind:
        task["kind"] = kind
    return task


def _options_1_to_5(body: str) -> list[str]:
    by_num: dict[int, str] = {}
    for num, raw in OPTION_BLOCK.findall(body):
        line = _squash(BLANK_ANSWER.sub("", raw))
        if line:
            by_num[int(num)] = line[:500]
    if len(by_num) < 3:
        by_num = {}
        for num, raw in INLINE_OPTION.findall(body):
            line = _squash(BLANK_ANSWER.sub("", raw))
            if line and int(num) not in by_num:
                by_num[int(num)] = line[:500]
    if len(by_num) < 3:
        return []
    return [by_num.get(idx, "") for idx in range(1, 6)]


def _phrase_options(body: str) -> list[str]:
    found = []
    for raw in (body or "").splitlines():
        line = BLANK_ANSWER.sub("", raw).strip()
        if not line or re.match(r"^\d{1,3}[.)]\s", line):
            continue
        if CAPS_WORD.search(line):
            found.append(_squash(line)[:500])
    if 4 <= len(found) <= 8:
        return found
    return []


def _looks_word_prompt(prompt: str) -> bool:
    text = (prompt or "").lower()
    if any(hint in text for hint in NUMBER_HINTS):
        return False
    return any(hint in text for hint in WORD_HINTS)


def format_stored_prompt(prompt: str) -> str:
    """Keep НН / «одна буква Н» on the instruction line; split instruction from the sentence."""
    text = str(prompt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = re.sub(
        rf"(?i)(пишется)\s*\n+\s*({WRITING_TARGET})\.?",
        r"\1 \2.",
        text,
    )
    text = re.sub(
        rf"({PROMPT_SENTENCE_TAIL}\.)[ \t]*\n*[ \t]*(?={SENTENCE_START})",
        r"\1\n\n",
        text,
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_instruction(text: str) -> tuple[str, str]:
    raw = BLANK_ANSWER.sub(" ", text or "")
    match = INSTRUCTION_END.search(raw)
    if not match:
        return "", raw
    stem = _squash(raw[: match.end()]).strip(" .")
    rest = re.sub(r"^[\s.]+", "", raw[match.end() :])
    return stem, rest


def _cut_before_option_list(text: str) -> str:
    match = OPTION_LIST_START.search(text or "")
    if match:
        return (text or "")[: match.start()]
    return text


def _cut_at_options(text: str, options: list[str]) -> str:
    cut = _cut_before_option_list(text)
    if cut != text:
        return cut
    compact = _squash(text)
    for option in options:
        if not option:
            continue
        option_c = _squash(option)
        index = compact.find(option_c)
        if index != -1:
            return compact[:index]
        index = text.find(option)
        if index != -1:
            return text[:index]
    return text


def _strip_prompt_tail(text: str, strip_number: bool) -> str:
    text = BLANK_ANSWER.sub(" ", text)
    text = re.sub(r"\bОтвет\b\s*:?\s*$", "", text, flags=re.I)
    if strip_number:
        text = TRAILING_TASK_NUM.sub("", text)
    return text.strip(" .")


def _format_passage(text: str) -> str:
    text = text or ""
    text = re.sub(
        r"(\S)[ \t]*\n+[ \t]*(\(\d+\)(?=[А-ЯЁA-Z«\"]))",
        r"\1\n\n\2",
        text,
        count=1,
    )
    text = re.sub(
        r"(\S)[ \t]+(\(\d+\)(?=[А-ЯЁA-Z«\"]))",
        r"\1\n\n\2",
        text,
        count=1,
    )
    parts = [_squash(part) for part in re.split(r"\n\s*\n", text)]
    return "\n\n".join(part for part in parts if part).strip()


def _headed_instruction(stem: str) -> str:
    text = (stem or "").strip()
    if text and not re.search(r"[.!?]$", text):
        return f"{text}."
    return text


def _task_prompt(body: str, options: list[str]) -> str:
    stem, rest = _split_instruction(body or "")
    if options:
        text = stem or _cut_at_options(BLANK_ANSWER.sub(" ", body or ""), options)
        text = _strip_prompt_tail(_squash(text), strip_number=True)
        return format_stored_prompt((text[:800] or EGE_PROMPT).strip())
    if stem:
        passage = _format_passage(rest)
        text = f"{_headed_instruction(stem)}\n\n{passage}" if passage else stem
        text = re.sub(r"\n{3,}", "\n\n", _strip_prompt_tail(text, strip_number=False))[:4000].strip()
        return format_stored_prompt(text)
    text = _format_passage(BLANK_ANSWER.sub(" ", body or ""))
    return format_stored_prompt(_strip_prompt_tail(text, strip_number=False)[:4000].strip())


def _normalize_key_text(raw: str) -> str:
    text = str(raw or "").strip(" .;,-")
    if not text or set(text) <= set("_-–—."):
        return ""
    if re.search(r"[A-Za-zА-Яа-яЁё]", text):
        return re.sub(r"\s+", " ", text).strip()
    if re.search(r"[,\s;]+", text):
        nums = [int(part) for part in re.findall(r"\d+", text)]
        return "".join(str(n) for n in sorted(set(nums))) if nums else ""
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if "0" not in digits and max(digits) <= "5" and len(digits) <= 5:
        return "".join(sorted(set(digits)))
    return digits


def _take_inline_answer(body: str) -> str:
    cleaned = BLANK_ANSWER.sub(" ", body or "")
    match = ANSWER_LINE.search(cleaned)
    if match:
        return _normalize_key_text(match.group(1))
    return ""


def _apply_answer_section(text: str, tasks: list[dict]) -> None:
    match = KEY_HEADING.search(text)
    if not match:
        return
    section = text[match.end() :]
    by_num = {}
    for num, ans in re.findall(r"(?m)^\s*(\d{1,3})[.)\s:–—-]+(.+?)\s*$", section):
        key = _normalize_key_text(ans)
        if key:
            by_num[int(num)] = key
    if len(by_num) < 2:
        return
    for task in tasks:
        if not task["answer"] and task["n"] in by_num:
            task["answer"] = by_num[task["n"]]


def build_bank(text: str, source_name: str, bank_id: str) -> dict:
    tasks = parse_tasks(text)
    stem = Path(source_name).stem.strip()
    title = stem[:80] if stem and stem.lower() not in {"uc", "download", "file"} else "Задания из PDF"
    return {
        "id": bank_id,
        "title": title,
        "source": source_name,
        "instruction": tasks[0]["prompt"] if tasks else EGE_PROMPT,
        "tasks": tasks,
    }


def looks_like_pdf_url(url: str) -> bool:
    raw = _strip_url_tail(url)
    if not raw.lower().startswith(("http://", "https://")):
        return False
    lowered = raw.lower()
    parsed = urlparse(raw)
    if parsed.path.lower().endswith(".pdf"):
        return True
    if re.search(r"drive\.google\.com/file/d/[a-zA-Z0-9_-]{20,}", raw):
        return True
    if "drive.google.com" in lowered and "id=" in lowered:
        return True
    if "docs.google.com" in lowered and "export=download" in lowered:
        return True
    if "dropbox.com" in lowered and (parsed.path.lower().endswith(".pdf") or "dl=" in lowered):
        return True
    return False


def _strip_url_tail(url: str) -> str:
    return re.sub(r"[),.;]+$", "", str(url or "").strip())


def canonical_source_url(url: str) -> str:
    return _strip_url_tail(url)


def rewrite_download_url(url: str) -> str:
    raw = _strip_url_tail(url)
    match = re.search(r"drive\.google\.com/file/d/([^/]+)", raw)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}&confirm=t"
    parsed = urlparse(raw)
    if "drive.google.com" in parsed.netloc or "docs.google.com" in parsed.netloc:
        file_id = (parse_qs(parsed.query).get("id") or [""])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
    if "dropbox.com" in parsed.netloc:
        if "dl=0" in raw:
            return raw.replace("dl=0", "dl=1")
        if "dl=" not in raw:
            glue = "&" if parsed.query else "?"
            return raw + glue + "dl=1"
    return raw


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Нужна ссылка http или https")
    if parsed.username or parsed.password:
        raise ValueError("Ссылку на этот адрес скачивать нельзя")
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host or host.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Ссылку на этот адрес скачивать нельзя")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("Ссылку на этот адрес скачивать нельзя")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Не удалось открыть ссылку") from exc
    if not infos:
        raise ValueError("Не удалось открыть ссылку")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Ссылку на этот адрес скачивать нельзя")


class _SafeRedirectHandler(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_pdf(url: str) -> tuple[bytes, str]:
    raw = _strip_url_tail(url)
    if not looks_like_pdf_url(raw):
        raise ValueError("По этой ссылке программа ждёт PDF")
    target = rewrite_download_url(raw)
    data, filename, content_type = _http_get(target)
    if data.startswith(b"%PDF"):
        return data, filename or "zadaniya.pdf"
    if "html" in content_type or data[:32].lstrip().lower().startswith(b"<!doctype") or b"<html" in data[:400].lower():
        retry = _drive_confirm_url(data.decode("utf-8", "replace"), target)
        if retry and retry != target:
            data, filename, content_type = _http_get(retry)
            if data.startswith(b"%PDF"):
                return data, filename or "zadaniya.pdf"
    raise ValueError("По ссылке не PDF. Скачайте файл и прикрепите плюсиком.")


def _drive_confirm_url(html: str, current: str) -> str:
    parsed = urlparse(current)
    file_id = (parse_qs(parsed.query).get("id") or [""])[0]
    if not file_id:
        match = re.search(r"/file/d/([^/]+)", html)
        file_id = match.group(1) if match else ""
    confirm = re.search(r"confirm=([0-9A-Za-z_-]+)", html)
    if file_id and confirm:
        return f"https://drive.google.com/uc?export=download&id={file_id}&confirm={confirm.group(1)}"
    return ""


def _http_get(url: str) -> tuple[bytes, str, str]:
    assert_public_http_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; JournalPDF/1.0)",
            "Accept": "application/pdf,*/*",
        },
        method="GET",
    )
    opener = build_opener(_SafeRedirectHandler)
    try:
        with opener.open(request, timeout=25) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            filename = _filename_from_headers(response.headers.get("Content-Disposition") or "", url)
            data = _read_limited(response)
    except HTTPError as exc:
        raise ValueError("Не удалось скачать файл по ссылке") from exc
    except (URLError, OSError) as exc:
        raise ValueError("Не удалось открыть ссылку") from exc
    return data, filename, content_type


def _read_limited(response) -> bytes:
    length = response.headers.get("Content-Length") or ""
    if length.isdigit() and int(length) > MAX_PDF_BYTES:
        raise ValueError("Файл слишком большой (до 20 МБ)")
    chunks = []
    total = 0
    while True:
        piece = response.read(64 * 1024)
        if not piece:
            break
        total += len(piece)
        if total > MAX_PDF_BYTES:
            raise ValueError("Файл слишком большой (до 20 МБ)")
        chunks.append(piece)
    return b"".join(chunks)


def _filename_from_headers(disposition: str, url: str) -> str:
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if match:
        name = Path(unquote(match.group(1))).name
        if name:
            return name
    match = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    if match:
        name = Path(match.group(1)).name
        if name:
            return name
    name = Path(urlparse(url).path).name
    return name if name.lower().endswith(".pdf") else ""


if __name__ == "__main__":
    raw_path = Path(__file__).resolve().parent / "data" / "ege-10-raw.txt"
    tasks = parse_tasks(raw_path.read_text(encoding="utf-8"))
    missing = [
        item["n"]
        for item in tasks
        if len(item["options"]) < 5 or any(not option for option in item["options"])
    ]
    print(f"raw tasks={len(tasks)} missing={len(missing)}")
    pdf_path = Path(__file__).resolve().parent / "data" / "source-10.2.pdf"
    if pdf_path.exists():
        bank = import_pdf_bytes(pdf_path.read_bytes(), "10.2.pdf", "pdf-test")
        miss = [
            item["n"]
            for item in bank["tasks"]
            if len(item["options"]) < 5 or any(not option for option in item["options"])
        ]
        print(f"pdf tasks={len(bank['tasks'])} missing={len(miss)} title={bank['title']}")
