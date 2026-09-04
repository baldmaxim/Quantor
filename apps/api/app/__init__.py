"""Quantor API — backend портала подсчёта строительных объёмов."""

__all__ = ["API_VERSION", "SCHEMA_VERSION"]

# Версия публичного HTTP-контракта (/api/v1).
API_VERSION = "v1"
# Версия схемы данных портала. Меняется вместе с моделью Project/Document/Revision/...
SCHEMA_VERSION = 1
