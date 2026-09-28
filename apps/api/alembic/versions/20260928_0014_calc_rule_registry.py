"""Расчётный контур: реестр правил

Revision ID: 0014_calc_rule_registry
Revises: 0013_calc_stage_p_inputs
Create Date: 2026-09-28

Реестр инженерных правил (ADR-0030, PROMPT 03) — три таблицы:

- `calc_rule_definitions` — стабильный ключ правила в пространстве (`vk.riser.vertical_length`).
  Ключ не содержит версии и не меняется;
- `calc_rule_versions` — версия правила: содержание по частям контракта (JSONB там, где
  вложенная структура), отпечаток содержания, статус и поля утверждения, вывода из действия и
  отклонения. Отдельная таблица на каждое свойство правила не заводится: строгую структуру
  держит контракт Pydantic, база хранит и защищает;
- `calc_rule_reviews` — журнал решений по версии: кто, когда, из какого статуса в какой, с каким
  комментарием и каким разбором опасностей старых правил. Общий журнал аудита здесь не
  годится: решение — часть происхождения правила и читается вместе с версией.

Правил старого портала здесь нет: 365 записей — карантинный каталог в данных пакета. Таблица
версий принимает только собственные статусы Quantor.

Неизменяемость — триггером базы, а не только сервисом:

- версию не в статусе DRAFT нельзя удалить;
- содержание утверждённой версии не меняется; из APPROVED можно только в DEPRECATED;
- устаревшая и отклонённая версии не меняются совсем;
- определение правила и журнал решений только дописываются.

Уникальные частичные индексы: один черновик и одна действующая утверждённая версия на правило.

Откат удаляет таблицы вместе с правилами: до этой ревизии хранить их было негде.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_calc_rule_registry"
down_revision: str | None = "0013_calc_stage_p_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISCIPLINES = ("VK", "OV", "EOM", "SS", "APT")
_STATUSES = ("DRAFT", "UNVERIFIED_LEGACY", "APPROVED", "DEPRECATED", "REJECTED")
_RULE_TYPES = (
    "PHYSICS",
    "GEOMETRY",
    "NORMATIVE",
    "MANUFACTURER",
    "ENGINEERING",
    "TENDER_ASSUMPTION",
)

# Тот же текст, что в `app/models/calc_rules.py`: тестовая база строится из моделей, бой — из
# миграций; совпадение триггеров проверяет test_schema_matches_migrations.
VERSION_GUARD_FUNCTION = """
create or replace function calc_rule_versions_guard() returns trigger
language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        if old.status <> 'DRAFT' then
            raise exception 'calc_rule_versions: % version cannot be deleted', old.status;
        end if;
        return old;
    end if;
    if new is not distinct from old then
        return new;
    end if;
    if (new.id, new.rule_id, new.version, new.created_at, new.created_by)
        is distinct from (old.id, old.rule_id, old.version, old.created_at, old.created_by) then
        raise exception 'calc_rule_versions: identity of a version is immutable';
    end if;
    if old.status = 'DRAFT' then
        if new.status not in ('DRAFT', 'APPROVED', 'REJECTED') then
            raise exception 'calc_rule_versions: transition % -> % is not allowed',
                old.status, new.status;
        end if;
        return new;
    end if;
    if old.status = 'APPROVED' and new.status in ('APPROVED', 'DEPRECATED')
        and (to_jsonb(new) - array['status', 'deprecated_at', 'deprecated_by',
                                   'deprecation_reason'])
            = (to_jsonb(old) - array['status', 'deprecated_at', 'deprecated_by',
                                     'deprecation_reason']) then
        return new;
    end if;
    raise exception 'calc_rule_versions: % version is immutable, create a new version',
        old.status;
end
$$
"""

VERSION_GUARD_TRIGGER = """
create trigger trg_calc_rule_versions_guard
before update or delete on calc_rule_versions
for each row execute function calc_rule_versions_guard()
"""

APPEND_ONLY_FUNCTION = """
create or replace function calc_rules_append_only() returns trigger
language plpgsql as $$
begin
    raise exception '% is append-only', tg_table_name;
end
$$
"""

DEFINITIONS_TRIGGER = """
create trigger trg_calc_rule_definitions_append_only
before update on calc_rule_definitions
for each row execute function calc_rules_append_only()
"""

REVIEWS_TRIGGER = """
create trigger trg_calc_rule_reviews_append_only
before update or delete on calc_rule_reviews
for each row execute function calc_rules_append_only()
"""


def _enum(values: Sequence[str], name: str, length: int) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def _jsonb(name: str, *, default: bool = True) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default="[]" if default else None,
        nullable=False,
    )


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "calc_rule_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=120), nullable=False),
        sa.Column("discipline", _enum(_DISCIPLINES, "calc_discipline", 8), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_calc_rule_definitions_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_rule_definitions")),
        sa.UniqueConstraint("workspace_id", "rule_key", name="uq_calc_rule_definitions_key"),
    )
    op.create_index(
        op.f("ix_calc_rule_definitions_created_at"), "calc_rule_definitions", ["created_at"]
    )

    op.create_table(
        "calc_rule_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum(_STATUSES, "calc_rule_status", 24),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("rule_type", _enum(_RULE_TYPES, "calc_rule_type", 24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("formula_text", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("implementation_key", sa.String(length=120), nullable=True),
        _jsonb("inputs"),
        _jsonb("parameters"),
        _jsonb("outputs", default=False),
        _jsonb("dimension_checks"),
        _jsonb("applicability", default=False),
        _jsonb("sources"),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        _jsonb("legacy_provenance"),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("edited_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_by", sa.Uuid(), nullable=True),
        sa.Column("deprecation_reason", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Uuid(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "(approved_at is not null) = (status in ('APPROVED', 'DEPRECATED'))",
            name=op.f("ck_calc_rule_versions_approval_consistent"),
        ),
        sa.CheckConstraint(
            "(deprecated_at is not null) = (status = 'DEPRECATED')",
            name=op.f("ck_calc_rule_versions_deprecation_consistent"),
        ),
        sa.CheckConstraint(
            "(rejected_at is not null) = (status = 'REJECTED')",
            name=op.f("ck_calc_rule_versions_rejection_consistent"),
        ),
        sa.CheckConstraint(
            "status in ('DRAFT', 'APPROVED', 'DEPRECATED', 'REJECTED')",
            name=op.f("ck_calc_rule_versions_own_statuses"),
        ),
        sa.CheckConstraint(
            "status not in ('APPROVED', 'DEPRECATED') or implementation_key is not null",
            name=op.f("ck_calc_rule_versions_approved_has_implementation"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name=op.f("ck_calc_rule_versions_title_not_blank")
        ),
        sa.CheckConstraint(
            "valid_from is null or valid_to is null or valid_from <= valid_to",
            name=op.f("ck_calc_rule_versions_valid_period"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_calc_rule_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["calc_rule_definitions.id"],
            name=op.f("fk_calc_rule_versions_rule_id_calc_rule_definitions"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_rule_versions")),
        sa.UniqueConstraint("rule_id", "version", name="uq_calc_rule_versions_version"),
    )
    op.create_index(op.f("ix_calc_rule_versions_created_at"), "calc_rule_versions", ["created_at"])
    op.create_index(
        "uq_calc_rule_versions_approved",
        "calc_rule_versions",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_index(
        "uq_calc_rule_versions_draft",
        "calc_rule_versions",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )

    op.create_table(
        "calc_rule_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", _enum(_STATUSES, "calc_rule_status", 24), nullable=False),
        sa.Column("to_status", _enum(_STATUSES, "calc_rule_status", 24), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        _jsonb("legacy_review"),
        _created_at(),
        sa.CheckConstraint(
            "from_status <> to_status", name=op.f("ck_calc_rule_reviews_changes_status")
        ),
        sa.CheckConstraint(
            "length(btrim(comment)) > 0", name=op.f("ck_calc_rule_reviews_comment_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["calc_rule_versions.id"],
            name=op.f("fk_calc_rule_reviews_rule_version_id_calc_rule_versions"),
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_rule_reviews")),
    )
    op.create_index(op.f("ix_calc_rule_reviews_created_at"), "calc_rule_reviews", ["created_at"])
    op.create_index(
        "ix_calc_rule_reviews_rule_version_id", "calc_rule_reviews", ["rule_version_id"]
    )

    # asyncpg не принимает несколько команд в одном подготовленном запросе.
    for statement in (
        APPEND_ONLY_FUNCTION,
        DEFINITIONS_TRIGGER,
        REVIEWS_TRIGGER,
        VERSION_GUARD_FUNCTION,
        VERSION_GUARD_TRIGGER,
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("drop trigger if exists trg_calc_rule_reviews_append_only on calc_rule_reviews")
    op.execute("drop trigger if exists trg_calc_rule_versions_guard on calc_rule_versions")
    op.execute(
        "drop trigger if exists trg_calc_rule_definitions_append_only on calc_rule_definitions"
    )
    op.execute("drop function if exists calc_rule_versions_guard()")
    op.execute("drop function if exists calc_rules_append_only()")

    op.drop_index("ix_calc_rule_reviews_rule_version_id", table_name="calc_rule_reviews")
    op.drop_index(op.f("ix_calc_rule_reviews_created_at"), table_name="calc_rule_reviews")
    op.drop_table("calc_rule_reviews")
    op.drop_index("uq_calc_rule_versions_draft", table_name="calc_rule_versions")
    op.drop_index("uq_calc_rule_versions_approved", table_name="calc_rule_versions")
    op.drop_index(op.f("ix_calc_rule_versions_created_at"), table_name="calc_rule_versions")
    op.drop_table("calc_rule_versions")
    op.drop_index(op.f("ix_calc_rule_definitions_created_at"), table_name="calc_rule_definitions")
    op.drop_table("calc_rule_definitions")
