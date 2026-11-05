"""Генерация Excel-шаблона каталога для команды данных."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from app.catalog_import.columns import SHEETS

INSTRUCTIONS_SHEET = "Инструкция"


def write_template(path: Path) -> None:
    workbook = Workbook()
    instructions = workbook.active
    instructions.title = INSTRUCTIONS_SHEET
    instructions.append(["Лист", "Колонка", "Обязательная", "Описание", "Пример"])

    for sheet_name, columns in SHEETS.items():
        sheet = workbook.create_sheet(sheet_name)
        sheet.append([column.name for column in columns])
        sheet.append([column.example for column in columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for column in columns:
            instructions.append(
                [
                    sheet_name,
                    column.name,
                    "да" if column.required else "нет",
                    column.description,
                    str(column.example),
                ]
            )

    for cell in instructions[1]:
        cell.font = Font(bold=True)
    for letter, width in zip("ABCDE", (12, 20, 14, 70, 40), strict=True):
        instructions.column_dimensions[letter].width = width
    workbook.save(path)
