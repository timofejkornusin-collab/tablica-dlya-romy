# -*- coding: utf-8 -*-
"""Собрать банк заданий ЕГЭ №10 из извлечённого текста PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "ege-10-raw.txt"
OUT = ROOT / "data" / "banks" / "ege-10.json"

PROMPT = (
    "Укажите варианты ответов, в которых во всех словах одного ряда "
    "пропущена одна и та же буква. Запишите номера ответов."
)


def parse(text: str) -> list[dict]:
    chunks = re.split(r"(?m)^(\d{1,3})\.Укажите", text)
    tasks = []
    # chunks: preamble, num, rest, num, rest...
    for i in range(1, len(chunks), 2):
        number = int(chunks[i])
        body = chunks[i + 1]
        body = re.sub(
            r"варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква\.\s*"
            r"Запишите номера ответов\.\s*Ответ:\s*_+\.\s*",
            "",
            body,
            flags=re.I,
        )
        options = []
        matches = re.findall(r"(?ms)^\s*([1-5])\.\s*(.*?)(?=^\s*[1-5]\.\s*|\Z)", body)
        by_num = {}
        for num, raw in matches:
            line = " ".join(raw.split())
            line = re.sub(r"\s*—\s*\d+\s+of\s+\d+\s*—", "", line).strip()
            if line:
                by_num[int(num)] = line
        for idx in range(1, 6):
            options.append(by_num.get(idx, ""))
        tasks.append(
            {
                "n": number,
                "prompt": PROMPT,
                "options": options,
                "answer": "",
            }
        )
    tasks.sort(key=lambda item: item["n"])
    return tasks


def main() -> None:
    text = RAW.read_text(encoding="utf-8")
    tasks = parse(text)
    missing = [item["n"] for item in tasks if len(item["options"]) < 5 or any(not opt for opt in item["options"])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": "ege-10",
        "title": "Задание 10 ЕГЭ",
        "source": "10.2.pdf",
        "instruction": PROMPT,
        "tasks": tasks,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"tasks={len(tasks)} missing_options={missing[:20]} count_missing={len(missing)}")


if __name__ == "__main__":
    main()
