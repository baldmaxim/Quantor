"""Замечание генератора: код, текст для человека и квартира, к которой оно относится."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    apartment: str | None = None
