"""Отпечаток геометрии DXF вида: перенос решений человека на новый прогон движка.

DXF вида побайтно не повторяется из-за метаданных (HEADER: время, GUID; порядок записей CLASSES;
строки автора в OBJECTS), но секции TABLES, BLOCKS и ENTITIES при повторном прогоне той же версией
совпадают побайтно (вместе с handles). Отпечаток - sha256 конкатенации этих секций в порядке
TABLES, BLOCKS, ENTITIES. Если любой из трёх секций нет, она не закрыта `ENDSEC`, `ENTITIES` пуста
или данные не декодируются как текстовый DXF (обрезанный и бинарный файл), отпечатка нет (`None`):
сравнивать нечего, решения не переносятся. BOM в начале файла игнорируется.

Разбор идёт по групповым парам «код / значение» (две строки), а не по подстроке: текст `SECTION`
или `ENDSEC` внутри значения секцией не считается. Хешируются байты строк (движок пишет DXF R2018 в
UTF-8); декодирование нужно только как проверка, что файл текстовый. Окончания строк `\\r\\n`
приводятся к `\\n`.
"""

from __future__ import annotations

import hashlib
from typing import Final

# Порядок секций в отпечатке фиксирован: он не зависит от порядка секций в файле.
FINGERPRINT_SECTIONS: Final = (b"TABLES", b"BLOCKS", b"ENTITIES")
_BOM: Final = b"\xef\xbb\xbf"
# Пустая секция: `0 SECTION`, `2 <имя>`, `0 ENDSEC` - ровно шесть строк.
_EMPTY_SECTION_LINES: Final = 6


def dxf_geometry_sha256(data: bytes) -> str | None:
    """sha256 секций TABLES, BLOCKS, ENTITIES текстового DXF; `None`, если файл неполный."""
    if data.startswith(_BOM):
        data = data[len(_BOM) :]
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = data.replace(b"\r\n", b"\n").split(b"\n")
    spans: dict[bytes, list[tuple[int, int]]] = {name: [] for name in FINGERPRINT_SECTIONS}
    total = len(lines) - len(lines) % 2
    start: int | None = None
    name: bytes | None = None
    index = 0
    while index < total:
        code, value = lines[index].strip(), lines[index + 1].strip()
        if start is None:
            # Имя секции - следующая пара `2 / <имя>`.
            if (
                code == b"0"
                and value == b"SECTION"
                and index + 3 < len(lines)
                and lines[index + 2].strip() == b"2"
            ):
                start = index
                name = lines[index + 3].strip()
        elif code == b"0" and value == b"ENDSEC":
            if name in spans:
                spans[name].append((start, index + 2))
            start = None
            name = None
        index += 2
    if any(not spans[section] for section in FINGERPRINT_SECTIONS):
        return None
    if all(end - begin <= _EMPTY_SECTION_LINES for begin, end in spans[b"ENTITIES"]):
        return None
    digest = hashlib.sha256()
    for section in FINGERPRINT_SECTIONS:
        for begin, end in spans[section]:
            for line in lines[begin:end]:
                digest.update(line)
                digest.update(b"\n")
    return digest.hexdigest()
