# -*- coding: utf-8 -*-
"""Импорт PDF заданий ЕГЭ 6–21 в структуру практики."""

from __future__ import annotations

import unittest
from pathlib import Path

import journal
import pdf_import

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path("/tmp/ege-pdfs")
FILES = {
    6: "Задание 6.pdf",
    7: "Задание 7.pdf",
    9: "Задание 9.pdf",
    10: "Задание 10.pdf",
    11: "Задание 11.pdf",
    12: "Задание 12.pdf",
    13: "Задание 13.pdf",
    14: "Задание 14.pdf",
    15: "Задание 15.pdf",
    16: "Задание 16.pdf",
    17: "Задание 17.pdf",
    18: "Задание 18.pdf",
    19: "Задание 19.pdf",
    20: "Задание 20.pdf",
    21: "Задание 21.pdf",
}


def load_bank(number: int) -> dict:
    path = FOLDER / FILES[number]
    return pdf_import.import_pdf_bytes(path.read_bytes(), path.name, f"pdf-ege{number}")


def blank_hits(task: dict) -> bool:
    blob = " ".join(
        [str(task.get("prompt") or "")]
        + [str(item) for item in (task.get("options") or [])]
    )
    return bool(pdf_import.BLANK_ANSWER.search(blob)) or "________" in blob


class SyntheticPdfImportTest(unittest.TestCase):
    def test_strips_blank_answer_and_keeps_pdf_instruction(self) -> None:
        text = (
            "1.Укажите варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. сп…ртакиада, прил…скать\n"
            "2. кап…шон, ж…ри\n"
            "3. верм…шель, экстр…мальный\n"
            "4. м…нталитет, ч…столюбивый\n"
            "5. игн…рировать, симп…тичный\n"
            "2.Укажите варианты ответов, в которых в обоих словах одного ряда пропущена одна и та же буква. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. опазд…вать, завед…вать\n"
            "2. владел…ц, эмал…вая\n"
            "3. старуш…чий, узорч…тый\n"
            "4. измельч…нный, стаж…рская\n"
            "5. досто…н, размаш…стый\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertTrue(all(len(task["options"]) == 5 for task in tasks))
        self.assertIn("во всех словах одного ряда", tasks[0]["prompt"])
        self.assertIn("в обоих словах одного ряда", tasks[1]["prompt"])
        self.assertNotIn("Ответ", tasks[0]["prompt"])
        self.assertNotRegex(tasks[0]["prompt"], r"\b1\s*$")
        self.assertTrue(tasks[0]["options"][0].startswith("сп"))
        self.assertFalse(journal.is_word_task(tasks[0]))

    def test_word_phrases_and_missing_letter(self) -> None:
        text = (
            "1.В одном из выделенных ниже слов допущена грамматическая ошибка. "
            "Исправьте ошибку и запишите слово правильно. Ответ: ________________.\n"
            "около ДВУХСТА деревьев\n"
            "пачка МАКАРОН\n"
            "петь ГРОМЧЕ всех\n"
            "КРАСИВЫЙ Сочи\n"
            "ЧИТАЯ поэму\n"
            "2.Отредактируйте предложение: исправьте лексическую ошибку, исключив лишнее слово. "
            "Запишите это слово. Ответ: ________________.\n"
            "Композитор Шопен выступал в концертах этой зимы.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertEqual(tasks[0].get("kind"), "phrases")
        self.assertEqual(tasks[0]["options"][0], "около ДВУХСТА деревьев")
        self.assertNotIn("ДВУХСТА", tasks[0]["prompt"])
        self.assertNotIn("Ответ", tasks[0]["prompt"])
        self.assertTrue(journal.is_word_task(tasks[0]))
        self.assertFalse(any(tasks[1]["options"]))
        self.assertIn("Шопен", tasks[1]["prompt"])
        self.assertNotIn("Ответ", tasks[1]["prompt"])
        self.assertTrue(journal.is_word_task(tasks[1]))

    def test_answer_without_colon_and_number_not_in_prompt(self) -> None:
        text = (
            "81.кажите варианты ответов, в которых НЕ с выделенным словом пишется СЛИТНО. "
            "Запишите номера ответов. Ответ______________.\n"
            "1. Процедура абсолютно (НЕ)СЛОЖНАЯ, но в ней важна каждая мелочь.\n"
            "2. Он молчал, стыдясь своей бесхарактерности и (НЕ)ГОДУЯ на себя.\n"
            "3. Вот две простые по формулировке, но (НЕ)РЕШЁННЫЕ до сих пор проблемы.\n"
            "4. Жизнь моей бабушки была далеко (НЕ)СЛАДКОЙ.\n"
            "5. Ветер качал ветви деревьев, стуча ими в (НЕ)ЗАНАВЕШЕННЫЕ окна.\n"
            "95. одном из выделенных ниже слов допущена грамматическая ошибка. "
            "Исправьте ошибку и запишите слово правильно. Ответ: __________.\n"
            "около ДВУХСТА деревьев\n"
            "пачка МАКАРОН\n"
            "петь ГРОМЧЕ всех\n"
            "КРАСИВЫЙ Сочи\n"
            "ЧИТАЯ поэму\n"
            "61 Укажите варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. сп…ртакиада, прил…скать\n"
            "2. кап…шон, ж…ри\n"
            "3. верм…шель, экстр…мальный\n"
            "4. м…нталитет, ч…столюбивый\n"
            "5. игн…рировать, симп…тичный\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [81, 95, 61])
        self.assertNotIn("Ответ", tasks[0]["prompt"])
        self.assertNotRegex(tasks[0]["prompt"], r"(?m)^\d{1,3}\.\s")
        self.assertNotRegex(tasks[0]["prompt"].rstrip(), r"\b\d{1,2}\s*$")
        self.assertEqual(len([item for item in tasks[0]["options"] if item]), 5)
        self.assertEqual(tasks[1].get("kind"), "phrases")
        self.assertIn("во всех словах одного ряда", tasks[2]["prompt"])

    def test_keys_heading_does_not_eat_option_about_keys(self) -> None:
        text = (
            "1.Укажите варианты ответов, в которых НЕ с выделенным словом пишется СЛИТНО. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. Процедура абсолютно (НЕ)СЛОЖНАЯ, но в ней важна каждая мелочь.\n"
            "2. Ключи до сих пор (НЕ)НАЙДЕНЫ.\n"
            "3. Вот две простые по формулировке, но (НЕ)РЕШЁННЫЕ до сих пор проблемы.\n"
            "4. Жизнь моей бабушки была далеко (НЕ)СЛАДКОЙ.\n"
            "5. Ветер качал ветви деревьев, стуча ими в (НЕ)ЗАНАВЕШЕННЫЕ окна.\n"
            "2.Укажите варианты ответов, в которых НЕ с выделенным словом пишется РАЗДЕЛЬНО. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. Это была далеко (НЕ) ЛЁГКАЯ задача.\n"
            "2. Он говорил (НЕ) ГРОМКО, но внятно.\n"
            "3. Книга ещё (НЕ) ПРОЧИТАНА.\n"
            "4. Передо мной лежал (НЕ) БОЛЬШОЙ, а маленький свёрток.\n"
            "5. Дом стоял (НЕ) ДАЛЕКО от реки.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual(tasks[0]["options"][1], "Ключи до сих пор (НЕ)НАЙДЕНЫ.")
        self.assertFalse(tasks[0]["answer"])
        self.assertFalse(journal.is_word_task(tasks[0]))

    def test_public_practice_keeps_answer_field_separate(self) -> None:
        text = (
            "1.В одном из выделенных ниже слов допущена грамматическая ошибка. "
            "Исправьте ошибку и запишите слово правильно. Ответ: ________________.\n"
            "около ДВУХСТА деревьев\n"
            "пачка МАКАРОН\n"
            "петь ГРОМЧЕ всех\n"
            "КРАСИВЫЙ Сочи\n"
            "ЧИТАЯ поэму\n"
            "2.Найдите предложения, в которых ставится тире. Запишите номера этих предложений. "
            "Ответ: ________________.\n"
            "(1)Я сидел в кают-компании. (2)Вдруг в дверь постучали.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        bank = {"id": "pdf-test", "title": "Задание 7", "instruction": tasks[0]["prompt"], "tasks": tasks}
        student = {"id": "s", "name": "рома", "progress": {}}
        payload = journal.public_practice(bank, student, "teacher")
        first = payload["tasks"][0]
        second = payload["tasks"][1]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["kind"], "phrases")
        self.assertTrue(first["word"])
        self.assertNotIn("Ответ", first["prompt"])
        self.assertEqual(first["options"][0], "около ДВУХСТА деревьев")
        self.assertEqual(second["n"], 2)
        self.assertIn("(1)Я сидел", second["prompt"])
        self.assertFalse(second["word"])

    def test_passage_keeps_parenthetical_numbers(self) -> None:
        text = (
            "1.Укажите цифру(-ы), на месте которой(-ых) пишется НН. Ответ: ________________.\n"
            "Все дома необыкнове(1)о приплюснуты, давно не штукатуре(2)ы, крыши не краше(3)ы, ставни затворе(4)ы.\n"
            "2.Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений. Ответ: ________________.\n"
            "(1)Я сидел в кают-компании, прислушиваясь в недоумении к свисту ветра между снастей. "
            "(2)Вдруг в дверь постучали.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertFalse(any(tasks[0]["options"]))
        self.assertIn("(1)", tasks[0]["prompt"])
        self.assertIn("необыкнове(1)о", tasks[0]["prompt"])
        self.assertNotIn("Ответ", tasks[0]["prompt"])
        self.assertIn("(1)Я сидел", tasks[1]["prompt"])
        self.assertIn("\n(1)", tasks[1]["prompt"])
        self.assertFalse(journal.is_word_task(tasks[0]))
        self.assertFalse(journal.is_word_task(tasks[1]))

    def test_ege10_raw_keeps_numbers_and_five_options(self) -> None:
        raw_path = ROOT / "data" / "ege-10-raw.txt"
        tasks = pdf_import.parse_tasks(raw_path.read_text(encoding="utf-8"))
        nums = [task["n"] for task in tasks]
        self.assertGreaterEqual(len(tasks), 90)
        self.assertEqual(nums[0], 1)
        self.assertTrue(all(len(task["options"]) == 5 for task in tasks[:10]))
        self.assertNotIn("Ответ", tasks[0]["prompt"])
        self.assertNotRegex(tasks[0]["prompt"].rstrip(), r"\b\d{1,2}\s*$")
        self.assertIn("пропущена одна и та же буква", tasks[0]["prompt"])


@unittest.skipUnless(all((FOLDER / name).is_file() for name in FILES.values()), "нет исходных PDF")
class RealPdfImportTest(unittest.TestCase):
    def test_every_file_has_stable_numbers_and_no_blank_answers(self) -> None:
        numbered = {9, 10, 11, 12, 13, 14, 16}
        phrases = {7}
        word_only = {6}
        passage = {15, 17, 18, 19, 20, 21}
        for ege, name in FILES.items():
            with self.subTest(file=name):
                bank = load_bank(ege)
                tasks = bank["tasks"]
                nums = [task["n"] for task in tasks]
                self.assertGreaterEqual(len(tasks), 90, nums[:5])
                self.assertEqual(nums[0], 1)
                self.assertEqual(len(nums), len(set(nums)))
                self.assertLessEqual(max(nums) - min(nums) + 1 - len(nums), 1)
                first = tasks[0]
                self.assertFalse(blank_hits(first), first["prompt"][:180])
                self.assertNotRegex(first["prompt"], r"(?m)^\d{1,3}\.\s")
                self.assertNotRegex(first["prompt"].rstrip(), r"\b\d{1,2}\s*$")
                filled = [item for item in (first.get("options") or []) if item]
                if ege in numbered:
                    self.assertEqual(len(filled), 5, first["options"])
                    self.assertNotIn(first["options"][0], first["prompt"])
                    self.assertFalse(journal.is_word_task(first))
                elif ege in phrases:
                    self.assertEqual(first.get("kind"), "phrases")
                    self.assertEqual(len(filled), 5)
                    self.assertIn("ДВУХСТА", first["options"][0])
                    self.assertNotIn("ДВУХСТА", first["prompt"])
                    self.assertTrue(journal.is_word_task(first))
                elif ege in word_only:
                    self.assertFalse(filled)
                    self.assertIn("Шопен", first["prompt"])
                    self.assertTrue(journal.is_word_task(first))
                elif ege in passage:
                    self.assertLess(len(filled), 3)
                    self.assertRegex(first["prompt"], r"\(\d\)")


if __name__ == "__main__":
    unittest.main()
