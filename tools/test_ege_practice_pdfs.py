# -*- coding: utf-8 -*-
"""Импорт PDF заданий ЕГЭ 6–21 в структуру практики."""

from __future__ import annotations

import re
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
        extra_word = [part.strip() for part in tasks[1]["prompt"].split("\n\n") if part.strip()]
        self.assertEqual(len(extra_word), 2, tasks[1]["prompt"])
        self.assertTrue(extra_word[0].endswith("Запишите это слово."))
        self.assertTrue(extra_word[1].startswith("Композитор Шопен"))

    def test_inline_word_and_long_keys_are_kept(self) -> None:
        text = (
            "1.В одном из выделенных ниже слов допущена грамматическая ошибка. "
            "Исправьте ошибку и запишите слово правильно. Ответ: ДВУХСТА.\n"
            "около ДВУХСТА деревьев\n"
            "пачка МАКАРОН\n"
            "петь ГРОМЧЕ всех\n"
            "КРАСИВЫЙ Сочи\n"
            "ЧИТАЯ поэму\n"
            "2.Укажите варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква. "
            "Запишите номера ответов. Ответ: ________________.\n"
            "1. сп…ртакиада, прил…скать\n"
            "2. кап…шон, ж…ри\n"
            "3. верм…шель, экстр…мальный\n"
            "4. м…нталитет, ч…столюбивый\n"
            "5. игн…рировать, симп…тичный\n"
            "Ключи ответов\n"
            "2. 245\n"
            "3. 5724613\n"
            "4. 2, 15, 18\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual(tasks[0]["answer"], "ДВУХСТА")
        self.assertEqual(tasks[1]["answer"], "245")
        filled = []
        pdf_import._apply_answer_section(
            "Ключи ответов\n3. 5724613\n4. 2, 15, 18\n",
            filled := [
                {"n": 3, "answer": ""},
                {"n": 4, "answer": ""},
            ],
        )
        self.assertEqual(filled[0]["answer"], "5724613")
        self.assertEqual(filled[1]["answer"], "21518")

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
        self.assertIn("\n\n", tasks[0]["prompt"])
        self.assertIn("\n\n", tasks[1]["prompt"])
        instruction, passage = tasks[0]["prompt"].split("\n\n", 1)
        self.assertTrue(instruction.endswith("НН."))
        self.assertTrue(passage.startswith("Все дома"))
        self.assertNotIn("НН.", passage)
        instruction2, passage2 = tasks[1]["prompt"].split("\n\n", 1)
        self.assertTrue(instruction2.rstrip(".").endswith("предложений"))
        self.assertTrue(passage2.startswith("(1)Я сидел"))
        self.assertIn("(2)Вдруг", passage2)
        self.assertNotIn("\n\n", passage2)
        self.assertFalse(journal.is_word_task(tasks[0]))
        self.assertFalse(journal.is_word_task(tasks[1]))

    def test_glued_instruction_does_not_share_line_with_options(self) -> None:
        text = (
            "1.Укажите варианты ответов, в которых во всех словах одного ряда пропущена одна и та же буква. "
            "Запишите номера ответов. Ответ: ________________.1. сп…ртакиада, прил…скать "
            "2. кап…шон, ж…ри 3. верм…шель, экстр…мальный 4. м…нталитет, ч…столюбивый "
            "5. игн…рировать, симп…тичный "
            "2.Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений. Ответ: ________________.(1)Я сидел в кают-компании. (2)Вдруг в дверь постучали."
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertEqual(len([item for item in tasks[0]["options"] if item]), 5)
        self.assertNotIn("сп…ртакиада", tasks[0]["prompt"])
        self.assertNotRegex(tasks[0]["prompt"], r"1[.)]")
        self.assertTrue(tasks[0]["options"][0].startswith("сп"))
        self.assertIn("\n\n", tasks[1]["prompt"])
        instruction, passage = tasks[1]["prompt"].split("\n\n", 1)
        self.assertNotIn("(1)", instruction)
        self.assertTrue(passage.startswith("(1)Я сидел"))

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


class PromptParagraphSplitTest(unittest.TestCase):
    def _parts(self, prompt: str) -> list[str]:
        return [part.strip() for part in re.split(r"\n\s*\n", prompt) if part.strip()]

    def test_task15_keeps_nn_on_instruction_when_wrapped(self) -> None:
        text = (
            "1.Укажите цифру(-ы), на месте которой(-ых) пишется\n"
            "НН. Все дома необыкнове(1)о приплюснуты, давно не штукатуре(2)ы, крыши не краше(3)ы, ставни затворе(4)ы.\n"
            "2.Укажите цифру(-ы), на месте которой(-ых) пишется\n"
            "одна буква Н. Надпись напомнила ему долгожда(1)ую телеграмму, написа(2)ую на си(3)ей стекля(3)ой табличке.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        first = self._parts(tasks[0]["prompt"])
        second = self._parts(tasks[1]["prompt"])
        self.assertEqual(len(first), 2, tasks[0]["prompt"])
        self.assertTrue(first[0].endswith("пишется НН."))
        self.assertTrue(first[1].startswith("Все дома"))
        self.assertNotIn("НН.", first[1])
        self.assertTrue(second[0].endswith("пишется одна буква Н."))
        self.assertTrue(second[1].startswith("Надпись напомнила"))
        self.assertNotIn("одна буква Н.", second[1])

    def test_format_stored_prompt_repairs_live_task15_and_17(self) -> None:
        fifteen = (
            "Укажите цифру(-ы), на месте которой(-ых) пишется\n\n"
            "НН. Все дома необыкнове(1)о приплюснуты, давно не штукатуре(2)ы, крыши не краше(3)ы, ставни затворе(4)ы"
        )
        fifteen_n = (
            "Укажите цифру(-ы), на месте которой(-ых) пишется\n\n"
            "одна буква Н. Надпись напомнила ему долгожда(1)ую телеграмму"
        )
        seventeen = (
            "Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). "
            "Войдя в номер (1) проезжий тотчас сбросил с себя шинель и шарф"
        )
        eighteen = (
            "Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). "
            "— Эй ты, — крикнул он (1) громко"
        )
        first = self._parts(pdf_import.format_stored_prompt(fifteen))
        self.assertEqual(first[0], "Укажите цифру(-ы), на месте которой(-ых) пишется НН.")
        self.assertTrue(first[1].startswith("Все дома"))
        second = self._parts(pdf_import.format_stored_prompt(fifteen_n))
        self.assertTrue(second[0].endswith("пишется одна буква Н."))
        self.assertTrue(second[1].startswith("Надпись напомнила"))
        comma = self._parts(pdf_import.format_stored_prompt(seventeen))
        self.assertTrue(comma[0].endswith("запятая(-ые)."))
        self.assertTrue(comma[1].startswith("Войдя в номер"))
        dashed = self._parts(pdf_import.format_stored_prompt(eighteen))
        self.assertTrue(dashed[0].endswith("запятая(-ые)."))
        self.assertTrue(dashed[1].startswith("— Эй ты"))
        again = pdf_import.format_stored_prompt(pdf_import.format_stored_prompt(fifteen))
        self.assertEqual(again, pdf_import.format_stored_prompt(fifteen))

    def test_task6_splits_instruction_from_sentence(self) -> None:
        chopped = (
            "Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. "
            "Запишите подобранное слово, соблюдая нормы современного русского литературного языка и сохраняя смысл высказывания. "
            "Учился Фредерик Шопен старательно и серьёзно, из всех предметов делал предпочтение истории и польской литературе"
        )
        short = (
            "Отредактируйте предложение: исправьте лексическую ошибку, исключив лишнее слово. "
            "Запишите это слово. Композитор Шопен выступал в концертах этой зимы."
        )
        language_only = (
            "Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. "
            "Запишите подобранное слово, соблюдая нормы современного русского литературного языка. "
            "Предельный срок подачи документов истекает завтра."
        )
        first = self._parts(pdf_import.format_stored_prompt(chopped))
        self.assertEqual(len(first), 2, first)
        self.assertTrue(first[0].endswith("смысл высказывания."))
        self.assertTrue(first[1].startswith("Учился Фредерик Шопен"))
        self.assertNotIn("Учился", first[0])
        second = self._parts(pdf_import.format_stored_prompt(short))
        self.assertTrue(second[0].endswith("Запишите это слово."))
        self.assertTrue(second[1].startswith("Композитор Шопен"))
        third = self._parts(pdf_import.format_stored_prompt(language_only))
        self.assertTrue(third[0].endswith("литературного языка."))
        self.assertTrue(third[1].startswith("Предельный срок"))
        again = pdf_import.format_stored_prompt(pdf_import.format_stored_prompt(chopped))
        self.assertEqual(again, pdf_import.format_stored_prompt(chopped))

    def test_task6_pdf_layout_splits_instruction_and_sentence(self) -> None:
        text = (
            "1.Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. "
            "Запишите подобранное слово, соблюдая нормы современного русского литературного языка и сохраняя смысл высказывания. "
            "Ответ: ________________.\n"
            "Учился Фредерик Шопен старательно и серьёзно, из всех предметов делал предпочтение истории и польской литературе.\n"
            "2.Отредактируйте предложение: исправьте лексическую ошибку, исключив лишнее слово. "
            "Выпишите это слово, соблюдая нормы современного русского литературного языка. Ответ: ________________.\n"
            "В своём сочинении я хотел показать значение спорта и почему я им увлекаюсь.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        first = self._parts(tasks[0]["prompt"])
        second = self._parts(tasks[1]["prompt"])
        self.assertEqual(len(first), 2, tasks[0]["prompt"])
        self.assertTrue(first[0].endswith("смысл высказывания."))
        self.assertTrue(first[1].startswith("Учился Фредерик Шопен"))
        self.assertNotIn("Учился", first[0])
        self.assertTrue(second[0].endswith("литературного языка."))
        self.assertTrue(second[1].startswith("В своём сочинении"))
        self.assertTrue(journal.is_word_task(tasks[0]))
        self.assertTrue(journal.is_word_task(tasks[1]))

    def test_task17_pdf_layout_splits_instruction_and_sentence(self) -> None:
        text = (
            "1.Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). Ответ: ________________.\n"
            "Войдя в номер (1) проезжий тотчас сбросил с себя шинель и шарф, сел на диван (2) и (3) опершись в колени кулаками (4) сперва поглядел кругом.\n"
            "2.Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). Ответ: ________________.\n"
            "Он не полностью видел Лежнева (1) стоявшего к свету спиною (2) и (3) с недоумением глядя на него (4) пытался разобраться в его чертах.\n"
        )
        tasks = pdf_import.parse_tasks(text)
        first = self._parts(tasks[0]["prompt"])
        second = self._parts(tasks[1]["prompt"])
        self.assertEqual(len(first), 2, tasks[0]["prompt"])
        self.assertTrue(first[0].endswith("запятая(-ые)."))
        self.assertTrue(first[1].startswith("Войдя в номер (1) проезжий"))
        self.assertTrue(second[1].startswith("Он не полностью видел Лежнева (1)"))
        self.assertNotIn("\n", first[0])
        self.assertNotIn("Войдя", first[0])

    def test_public_practice_repairs_already_imported_prompts(self) -> None:
        bank = {
            "id": "pdf-live",
            "title": "Задание 15",
            "instruction": "Укажите цифру(-ы), на месте которой(-ых) пишется\n\nНН. Все дома",
            "tasks": [
                {
                    "n": 1,
                    "prompt": "Укажите цифру(-ы), на месте которой(-ых) пишется\n\nНН. Все дома необыкнове(1)о приплюснуты.",
                },
                {
                    "n": 2,
                    "prompt": "Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). Войдя в номер (1) проезжий тотчас сбросил шинель.",
                },
                {
                    "n": 3,
                    "prompt": (
                        "Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. "
                        "Запишите подобранное слово, соблюдая нормы современного русского литературного языка и сохраняя смысл высказывания. "
                        "Учился Фредерик Шопен старательно и серьёзно."
                    ),
                },
            ],
        }
        payload = journal.public_practice(bank, {"id": "s", "name": "рома", "progress": {}}, "teacher")
        first = self._parts(payload["tasks"][0]["prompt"])
        second = self._parts(payload["tasks"][1]["prompt"])
        third = self._parts(payload["tasks"][2]["prompt"])
        self.assertTrue(first[0].endswith("пишется НН."))
        self.assertTrue(first[1].startswith("Все дома"))
        self.assertTrue(second[0].endswith("запятая(-ые)."))
        self.assertTrue(second[1].startswith("Войдя в номер"))
        self.assertTrue(third[0].endswith("смысл высказывания."))
        self.assertTrue(third[1].startswith("Учился Фредерик Шопен"))
        self.assertTrue(self._parts(payload["instruction"])[0].endswith("пишется НН."))

    def test_task21_splits_instruction_from_numbered_passage(self) -> None:
        glued = (
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений. (1) Я сидел в кают-компании, прислушиваясь в недоумении к свисту ветра "
            "между снастей и к ударам волн в бока судна. (2)Вдруг раздался пронзительный свист боцманских свистков, "
            "и вслед за тем разнёсся по всем палубам крик десяти голосов: «Пошёл все наверх!»"
        )
        pdf_style = (
            "Найдите предложения, в которых тире ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений. (1)17 февраля Россия празднует день рождения Агнии Барто — самой любимой детской писательницы. "
            "(2)Агния Барто — автор многих известных стихотворений."
        )
        inside_word = (
            "Укажите цифру(-ы), на месте которой(-ых) пишется НН. "
            "Все дома необыкнове(1)о приплюснуты, давно не штукатуре(2)ы."
        )
        first = self._parts(pdf_import.format_stored_prompt(glued))
        self.assertEqual(len(first), 2, first)
        self.assertTrue(first[0].endswith("предложений."))
        self.assertTrue(first[1].startswith("(1) Я сидел"))
        self.assertIn("(2)Вдруг", first[1])
        self.assertNotIn("(1)", first[0])
        second = self._parts(pdf_import.format_stored_prompt(pdf_style))
        self.assertTrue(second[0].endswith("предложений."))
        self.assertTrue(second[1].startswith("(1)17 февраля"))
        nn = pdf_import.format_stored_prompt(inside_word)
        self.assertIn("необыкнове(1)о", nn.split("\n\n", 1)[1])
        self.assertNotIn("\n\n(1)", nn)
        again = pdf_import.format_stored_prompt(pdf_import.format_stored_prompt(glued))
        self.assertEqual(again, pdf_import.format_stored_prompt(glued))

        bank = {
            "id": "pdf-21",
            "title": "Задание 21",
            "instruction": glued,
            "tasks": [{"n": 1, "prompt": glued}],
        }
        payload = journal.public_practice(bank, {"id": "s", "name": "рома", "progress": {}}, "teacher")
        shown = self._parts(payload["tasks"][0]["prompt"])
        self.assertTrue(shown[0].endswith("предложений."))
        self.assertTrue(shown[1].startswith("(1) Я сидел"))

        live_broken = (
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений.\n\n"
            "(1)Я сидел в кают-компании, прислушиваясь в недоумении к свисту ветра между снастей и к ударам волн в бока судна.\n\n"
            "(2)Вдруг раздался пронзительный свист боцманских свистков, и вслед за тем разнёсся по всем палубам крик десяти голосов: «Пошёл все наверх!» (3)Мгновенно всё народонаселение фрегата бросилось снизу вверх."
        )
        live_parts = self._parts(pdf_import.format_stored_prompt(live_broken))
        self.assertEqual(len(live_parts), 2, live_parts)
        self.assertTrue(live_parts[0].endswith("предложений."))
        self.assertTrue(live_parts[1].startswith("(1)Я сидел"))
        self.assertIn("(2)Вдруг", live_parts[1])
        self.assertIn("(3)Мгновенно", live_parts[1])
        self.assertNotIn("\n", live_parts[1])

        live_lines = (
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений.\n\n"
            "(1)Я сидел в кают-компании, прислушиваясь в недоумении к свисту ветра между снастей и к ударам волн в бока судна.\n"
            "(2)Вдруг раздался пронзительный свист боцманских свистков.\n"
            "(3)Мгновенно всё народонаселение фрегата бросилось снизу вверх."
        )
        lined = self._parts(pdf_import.format_stored_prompt(live_lines))
        self.assertEqual(len(lined), 2, lined)
        self.assertTrue(lined[1].startswith("(1)Я сидел"))
        self.assertIn("(2)Вдруг", lined[1])
        self.assertIn("(3)Мгновенно", lined[1])
        self.assertNotIn("\n", lined[1])

        live_task2 = (
            "Найдите предложения, в которых тире ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений.\n\n"
            "(1)17 февраля Россия празднует день рождения Агнии Барто — самой любимой детской писательницы.\n\n"
            "(2)Агния Барто — автор многих известных стихотворений.\n\n"
            "(3)«Наша Таня громко плачет…», «Мы с Тамарой» — все эти стихотворения написаны ею. "
            "(4)Они из нашего детства — мы знаем многие строки наизусть. "
            "(5)Агния Барто — одна из популярных детских поэтесс в стране. "
            "(6)Наряду с К. И. Чуковским и С. Я. Маршаком её произведения издавались огромными тиражами, входили в хрестоматии."
        )
        two = self._parts(pdf_import.format_stored_prompt(live_task2))
        self.assertEqual(len(two), 2, two)
        self.assertTrue(two[0].endswith("предложений."))
        self.assertTrue(two[1].startswith("(1)17 февраля"))
        self.assertIn("(2)Агния Барто", two[1])
        self.assertIn("(3)«Наша Таня", two[1])
        self.assertIn("(4)Они из нашего", two[1])
        self.assertIn("(5)Агния Барто", two[1])
        self.assertIn("(6)Наряду", two[1])
        self.assertNotIn("\n", two[1])

    def test_frontend_keeps_format_stored_prompt(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function formatStoredPrompt(text)", app_js)
        self.assertIn(r"запятая\(-ые\)", app_js)
        self.assertIn(r"одна\s+буква\s+Н", app_js)
        self.assertIn("смысл высказывания", app_js)
        self.assertIn("литературного языка", app_js)
        self.assertIn(r"\(\d+\)\s*", app_js)
        self.assertIn("task-skip-tight", app_js)
        self.assertIn("task-prompt-flow", app_js)
        self.assertIn("task.passage", app_js)
        self.assertNotIn("breakSentences", app_js)
        self.assertIn(".task-skip-tight", styles)
        self.assertIn(".task-prompt-flow", styles)
        self.assertIn("body.practice-open #page-subtitle", styles)
        self.assertIn('setPageSubtitle("");', app_js)

    def test_js_format_stored_prompt_matches_python(self) -> None:
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("нет node")
        app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        start = app.index("function formatStoredPrompt")
        end = app.index("function formatTaskPrompt")
        samples = [
            "Укажите цифру(-ы), на месте которой(-ых) пишется\n\nНН. Все дома необыкнове(1)о приплюснуты.",
            "Укажите цифру(-ы), на месте которой(-ых) пишется\n\nодна буква Н. Надпись напомнила ему телеграмму",
            "Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). Войдя в номер (1) проезжий тотчас сбросил шинель.",
            "Укажите цифру(-ы), на месте которой(-ых) должна(-ы) стоять запятая(-ые). — Эй ты, — крикнул он (1) громко",
            "Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. Запишите подобранное слово, соблюдая нормы современного русского литературного языка и сохраняя смысл высказывания. Учился Фредерик Шопен старательно и серьёзно.",
            "Отредактируйте предложение: исправьте лексическую ошибку, исключив лишнее слово. Запишите это слово. Композитор Шопен выступал в концертах этой зимы.",
            "Отредактируйте предложение: исправьте лексическую ошибку, заменив употреблённое неверно слово. Запишите подобранное слово, соблюдая нормы современного русского литературного языка. Предельный срок подачи документов истекает завтра.",
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. Запишите номера этих предложений. (1) Я сидел в кают-компании. (2)Вдруг раздался крик: «Пошёл все наверх!»",
            "Найдите предложения, в которых тире ставится в соответствии с одним и тем же правилом пунктуации. Запишите номера этих предложений. (1)17 февраля Россия празднует день рождения Агнии Барто.",
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. Запишите номера этих предложений.\n\n(1)Я сидел в кают-компании, прислушиваясь в недоумении к свисту ветра между снастей и к ударам волн в бока судна.\n\n(2)Вдруг раздался пронзительный свист боцманских свистков.",
            "Найдите предложения, в которых тире ставится в соответствии с одним и тем же правилом пунктуации. Запишите номера этих предложений.\n\n(1)17 февраля Россия празднует день рождения Агнии Барто — самой любимой детской писательницы.\n\n(2)Агния Барто — автор многих известных стихотворений.\n\n(3)«Наша Таня громко плачет…», «Мы с Тамарой» — все эти стихотворения написаны ею. (4)Они из нашего детства — мы знаем многие строки наизусть.",
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. Запишите номера этих предложений.\n\n(1)Я сидел в кают-компании.\n(2)Вдруг раздался свист.\n(3)Мгновенно всё бросилось вверх.",
            "Самостоятельно подберите указательное местоимение, которое должно стоять на месте пропуска в предпоследнем предложении текста. Запишите это местоимение. Не стану описывать оренбургскую осаду.",
        ]
        script = (
            app[start:end]
            + "const samples = "
            + json.dumps(samples, ensure_ascii=False)
            + ";\nfor (const item of samples) console.log(JSON.stringify(formatStoredPrompt(item)));\n"
        )
        result = subprocess.run(
            [node, "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), len(samples))
        for raw, line in zip(samples, lines):
            self.assertEqual(json.loads(line), pdf_import.format_stored_prompt(raw))

    def test_render_task21_passage_stays_one_wrapping_paragraph(self) -> None:
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("нет node")
        app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        start = app.index("function escapeHtml")
        end = app.index("function linkifyText")
        sample = (
            "Найдите предложения, в которых двоеточие ставится в соответствии с одним и тем же правилом пунктуации. "
            "Запишите номера этих предложений.\n\n"
            "(1)Я сидел в кают-компании.\n"
            "(2)Вдруг раздался свист.\n"
            "(3)Мгновенно всё бросилось вверх."
        )
        script = (
            app[start:end]
            + "const html = renderTaskPrompt("
            + json.dumps(sample, ensure_ascii=False)
            + ");\nconsole.log(html);\n"
        )
        result = subprocess.run(
            [node, "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        html = result.stdout
        self.assertIn('class="task-prompt task-prompt-flow"', html)
        self.assertIn("(1)Я сидел", html)
        self.assertIn("(2)Вдруг", html)
        self.assertIn("(3)Мгновенно", html)
        self.assertNotIn("<br>", html)
        self.assertNotIn("<br/>(2)", html)
        self.assertEqual(html.count("<p "), 2)


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


SEED_DIR = ROOT / "seed-pdfs"
SEED_FILES = {1: "ege-1.pdf", 2: "ege-2.pdf", 3: "ege-3.pdf"}


class Task123StructureTest(unittest.TestCase):
    def test_task1_splits_instruction_from_text(self) -> None:
        text = (
            "1.Самостоятельно подберите указательное местоимение, которое должно стоять на месте пропуска в "
            "предпоследнем предложении текста. Запишите это местоимение. Ответ__________. "
            "Не стану описывать оренбургскую осаду, которая принадлежит истории, а не семейственным запискам. "
            "(По А. С. Пушкину)\n"
            "2.Самостоятельно подберите ограничительно-выделительную частицу, которая должна стоять на месте "
            "пропуска в первом абзаце текста. Запишите эту частицу. Ответ__________. "
            "Для Пушкина характерна не встречаемая, кроме него, нигде и ни у кого черта художественного гения. "
            "(Из Пушкинской речи Ф. М. Достоевского)\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertTrue(journal.is_word_task(tasks[0]))
        self.assertFalse(tasks[0].get("options"))
        parts = [part.strip() for part in tasks[0]["prompt"].split("\n\n") if part.strip()]
        self.assertEqual(len(parts), 2, parts)
        self.assertTrue(parts[0].endswith("местоимение."))
        self.assertTrue(parts[1].startswith("Не стану описывать"))
        self.assertNotIn("Ответ", tasks[0]["prompt"])

    def test_task2_keeps_definitions_then_passage(self) -> None:
        text = (
            "1.В тексте выделено пять слов. Укажите варианты ответов, в которых лексическое значение "
            "выделенного слова соответствует его значению в данном тексте. Ответ____________.\n"
            "1. ОПИСЫВАТЬ. что. Составлять полный перечень вещей, бумаг и т. п. с целью учёта. Описывать инвентарь, имущество.\n"
            "2. ИСТОРИЯ. разговорное. Происшествие, событие, случай. Рассказать о какой-либо истории.\n"
            "3. ЗАПИСКИ. только множественное. Чьи-либо наблюдения, замечания, воспоминания и т. п. Путевые записки.\n"
            "4. ПИЩА. То, что служит источником чего-либо, даёт материал духовной деятельности. Духовная пища.\n"
            "5. ОБРАЗ. чего. Характер, склад, направление чего-либо. Образ жизни. Наш образ мыслей сходен.\n"
            "Не стану описывать оренбургскую осаду, которая принадлежит истории, а не семейственным запискам. "
            "(По А. С. Пушкину)\n"
            "2.В тексте выделено пять слов. Укажите варианты ответов, в которых лексическое значение "
            "выделенного слова соответствует его значению в данном тексте. Ответ____________.\n"
            "1. ЧУЖОЙ. Являющийся собственностью другого. Оставить на хранение чужие вещи.\n"
            "2. ЗНАЧЕНИЕ. Важность, значительность. Историческое значение.\n"
            "3. ЗАКЛЮЧАТЬ. Заканчивать, завершать. Заключать речь призывом.\n"
            "4. ПРОЯВИТЬ. Обнаружить своё свойство. Проявить храбрость.\n"
            "5. ЧЕРТА. Типичная особенность. Характерная черта личности.\n"
            "Для Пушкина характерна черта художественного гения. (Из Пушкинской речи Ф. М. Достоевского)\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertFalse(journal.is_word_task(tasks[0]))
        self.assertEqual(len([item for item in tasks[0]["options"] if item]), 5)
        self.assertTrue(tasks[0]["options"][0].startswith("ОПИСЫВАТЬ."))
        self.assertIn("Не стану описывать", tasks[0].get("passage") or "")
        self.assertNotIn("Не стану описывать", tasks[0]["options"][4])
        payload = journal.public_practice(
            {"id": "pdf-ege2", "title": "Задание 2", "instruction": tasks[0]["prompt"], "tasks": tasks},
            {"id": "s", "name": "рома", "progress": {}},
            "teacher",
        )
        self.assertIn("Не стану описывать", payload["tasks"][0].get("passage") or "")

    def test_task3_keeps_statements_then_passage(self) -> None:
        text = (
            "1. Укажите варианты ответов, в которых даны верные характеристики текста. Запишите номера ответов. Ответ____________.\n"
            "1. В тексте отсутствует эмоционально окрашенная лексика, слова используются в прямом значении.\n"
            "2. Логичное и последовательное изложение материала достигается за счёт сложных предложений.\n"
            "3. Текст содержит слова определённой тематической группы (осаду, пехота, артиллерия).\n"
            "4. Текст характеризуется типичной для официально-делового стиля точностью речи.\n"
            "5. Текст относится к научному стилю, так как основная цель автора — передача информации.\n"
            "Не стану описывать оренбургскую осаду, которая принадлежит истории, а не семейственным запискам. "
            "(По А. С. Пушкину)\n"
            "2. Укажите варианты ответов, в которых даны верные характеристики текста. Запишите номера ответов. Ответ____________.\n"
            "1. Текст относится к публицистическому стилю.\n"
            "2. Жанр текста — публичное выступление.\n"
            "3. Характерные слова с морфемой все- относятся к общественно-политической лексике.\n"
            "4. Выразительность текста обеспечивается синтаксическими средствами.\n"
            "5. Использование эпитетов позволяет усилить эмоциональность высказывания.\n"
            "Для Пушкина характерна черта художественного гения. (Из Пушкинской речи Ф. М. Достоевского)\n"
        )
        tasks = pdf_import.parse_tasks(text)
        self.assertEqual([task["n"] for task in tasks], [1, 2])
        self.assertFalse(journal.is_word_task(tasks[0]))
        self.assertEqual(len([item for item in tasks[0]["options"] if item]), 5)
        self.assertIn("номера ответов", tasks[0]["prompt"])
        self.assertIn("Не стану описывать", tasks[0].get("passage") or "")
        self.assertNotIn("Не стану описывать", " ".join(tasks[0]["options"]))


@unittest.skipUnless(all((SEED_DIR / name).is_file() for name in SEED_FILES.values()), "нет PDF заданий 1–3")
class SeedTask123PdfTest(unittest.TestCase):
    def test_seed_pdfs_match_file_structure(self) -> None:
        expected = {
            1: {"word": True, "options": False, "prompt": "Самостоятельно подберите", "text": "Не стану описывать"},
            2: {"word": False, "options": True, "prompt": "лексическое значение", "text": "Не стану описывать"},
            3: {"word": False, "options": True, "prompt": "верные характеристики текста", "text": "Не стану описывать"},
        }
        for number, name in SEED_FILES.items():
            with self.subTest(file=name):
                path = SEED_DIR / name
                bank = pdf_import.import_pdf_bytes(path.read_bytes(), f"Задание {number}.pdf", f"pdf-ege{number}")
                self.assertEqual(bank["title"], f"Задание {number}")
                tasks = bank["tasks"]
                self.assertGreaterEqual(len(tasks), 90)
                self.assertEqual([task["n"] for task in tasks], list(range(1, len(tasks) + 1)))
                first = tasks[0]
                want = expected[number]
                self.assertEqual(journal.is_word_task(first), want["word"])
                filled = [item for item in (first.get("options") or []) if item]
                if want["options"]:
                    self.assertEqual(len(filled), 5)
                    self.assertIn(want["text"], first.get("passage") or "")
                    self.assertNotIn(want["text"], filled[4])
                else:
                    self.assertFalse(filled)
                    self.assertIn(want["text"], first["prompt"])
                    parts = [part.strip() for part in first["prompt"].split("\n\n") if part.strip()]
                    self.assertEqual(len(parts), 2)
                self.assertIn(want["prompt"], first["prompt"])
                self.assertNotIn("________", first["prompt"])


if __name__ == "__main__":
    unittest.main()
