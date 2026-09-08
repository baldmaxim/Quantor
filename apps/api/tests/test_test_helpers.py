"""Проверки самих тестовых помощников.

Нужны по конкретной причине. Помощники вроде `clean_settings` вызываются почти только
из тестов базы данных, а те пропускаются на машине без PostgreSQL. Опечатка в помощнике
живёт до первого прогона на настоящей базе — и один такой случай уже был: повторный
именованный аргумент, обычный TypeError, не видимый локально ни одним запуском.

Здесь помощники вызываются без базы. Это дёшево и ловит ровно тот класс ошибок.
"""

from __future__ import annotations

import pytest

from app.domain import Role
from tests.conftest import clean_settings, make_context, oidc_settings


def test_clean_settings_neutralises_the_environment() -> None:
    settings = clean_settings()

    assert settings.tenderhub_enabled is False
    assert settings.feature_flags == ""
    assert settings.settings_overrides == ""


@pytest.mark.parametrize(
    "field",
    ["settings_overrides", "feature_flags"],
)
def test_clean_settings_accepts_an_override_of_a_field_it_zeroes(field: str) -> None:
    """Переопределение обнуляемого поля не должно приводить к двойному аргументу.

    Ровно на этом помощник и падал: значение задавалось и в теле, и вызывающим.
    """
    settings = clean_settings(**{field: "documents.content_url_ttl_seconds=300"})

    assert getattr(settings, field) == "documents.content_url_ttl_seconds=300"


def test_oidc_settings_enables_the_provider() -> None:
    settings = oidc_settings()

    assert settings.auth_mode == "oidc"
    assert settings.oidc_issuer
    assert settings.oidc_client_id


def test_make_context_derives_permissions_from_the_role() -> None:
    """Права выводятся из роли, а не перечисляются руками.

    Иначе проверка доступа сверяла бы выдуманный набор с действующим кодом и молчала бы
    именно тогда, когда состав роли поменяли.
    """
    from app.auth.permissions import permissions_for

    for role in Role:
        context = make_context(role)
        assert context.permissions == permissions_for(role), role
        assert context.role is role
