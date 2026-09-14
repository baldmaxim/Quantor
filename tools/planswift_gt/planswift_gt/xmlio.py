"""Чтение XML PlanSwift: кодировка и безопасный разбор.

PlanSwift объявляет `encoding="UTF-8"`, а пишет в Windows-1251. Порядок: BOM → объявленная
кодировка, если она не UTF-8 → строгий UTF-8 → контролируемый откат на cp1251. Откат считается,
а не скрывается: доля таких файлов — часть отчёта импорта.

Архив недоверенный: DOCTYPE и сущности отвергаются до разбора, размер файла ограничен.
"""

from __future__ import annotations

import codecs
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MAX_XML_BYTES = 32 * 1024 * 1024

_DECLARATION = re.compile(rb"^\s*<\?xml[^>]*encoding=[\"']([A-Za-z0-9._-]+)[\"'][^>]*\?>")
_DECLARATION_TEXT = re.compile(r"^\s*<\?xml[^>]*\?>")
_FORBIDDEN = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


class XmlRejectedError(ValueError):
    """Файл не может быть разобран; `reason` — машинный код причины."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Decoded:
    text: str
    # Кодировка, которой файл реально прочитан.
    encoding: str
    # Объявленная в заголовке; `None` — объявления нет.
    declared: str | None
    # Прочитан откатом на cp1251 вопреки объявлению UTF-8.
    fallback: bool


def _normalize(name: str) -> str:
    try:
        return codecs.lookup(name).name
    except LookupError:
        return name.lower()


def decode(raw: bytes) -> Decoded:
    if len(raw) > MAX_XML_BYTES:
        raise XmlRejectedError("xml_too_large", f"{len(raw)} байт, предел {MAX_XML_BYTES}")

    match = _DECLARATION.match(raw[:512])
    declared = match.group(1).decode("ascii") if match else None

    if raw.startswith(codecs.BOM_UTF8):
        return Decoded(_strict(raw[3:], "utf-8"), "utf-8", declared, fallback=False)
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return Decoded(_strict(raw, "utf-16"), "utf-16", declared, fallback=False)

    if declared is not None and _normalize(declared) != "utf-8":
        encoding = _normalize(declared)
        return Decoded(_strict(raw, encoding), encoding, declared, fallback=False)

    try:
        return Decoded(raw.decode("utf-8"), "utf-8", declared, fallback=False)
    except UnicodeDecodeError:
        pass
    return Decoded(_strict(raw, "cp1251"), "cp1251", declared, fallback=True)


def _strict(raw: bytes, encoding: str) -> str:
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as error:
        raise XmlRejectedError("undecodable", f"{encoding}: {error}") from error


def parse_text(text: str) -> ET.Element:
    """Разбирает уже декодированный текст. Объявление снимается: кодировка уже применена."""
    if _FORBIDDEN.search(text):
        raise XmlRejectedError(
            "forbidden_dtd", "DOCTYPE и сущности в разметке PlanSwift не ожидаются"
        )
    body = _DECLARATION_TEXT.sub("", text, count=1)
    try:
        return ET.fromstring(body)  # noqa: S314 — DTD отвергнут выше
    except ET.ParseError as error:
        raise XmlRejectedError("xml_parse_error", str(error)) from error
