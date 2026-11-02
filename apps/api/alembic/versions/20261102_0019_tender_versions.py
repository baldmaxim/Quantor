"""Версия тендера: замороженный комплект ревизий

Revision ID: 0019_tender_versions
Revises: 0018_local_auth
Create Date: 2026-11-02

ADR-0035, этап M2. Две таблицы:

- `tender_versions` — версия тендера проекта: номер, подпись, необязательная связь со строкой
  HUBTender (`external_tender_id`, `external_version`), статус `draft` / `frozen` и отпечаток
  комплекта `manifest_sha256` с отметкой заморозки. Не больше одного черновика на проект
  (частичный уникальный индекс); замороженная версия требует отпечаток и время заморозки;
- `tender_version_documents` — состав версии: по одной ревизии на документ, раздел комплекта и
  участие в модели. Ревизия защищена от удаления внешним ключом RESTRICT.

Неизменяемость — триггерами базы (образец — `calc_rule_versions`, миграция 0014): замороженную
версию нельзя изменить и удалить; состав замороженной версии нельзя ни дополнить, ни изменить, ни
сократить.

Существующие проекты версий не получают: подставлять несуществующую историю нельзя.

Откат удаляет таблицы вместе с версиями: до этой ревизии хранить их было негде.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_tender_versions"
down_revision: str | None = "0018_local_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тот же текст, что в `app/models/tender_version.py`: тестовая база строится из моделей, бой — из
# миграций; совпадение триггеров проверяет test_schema_matches_migrations.
VERSION_GUARD_FUNCTION = """
create or replace function tender_versions_guard() returns trigger
language plpgsql as $$
begin
    if old.status = 'frozen' then
        raise exception 'tender_versions: frozen version is immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end
$$
"""

VERSION_GUARD_TRIGGER = """
create trigger trg_tender_versions_guard
before update or delete on tender_versions
for each row execute function tender_versions_guard()
"""

DOCUMENTS_GUARD_FUNCTION = """
create or replace function tender_version_documents_guard() returns trigger
language plpgsql as $$
begin
    if tg_op <> 'INSERT' and exists (
        select 1 from tender_versions
         where id = old.tender_version_id and status = 'frozen'
    ) then
        raise exception 'tender_version_documents: composition of a frozen version is immutable';
    end if;
    if tg_op <> 'DELETE' and exists (
        select 1 from tender_versions
         where id = new.tender_version_id and status = 'frozen'
    ) then
        raise exception 'tender_version_documents: composition of a frozen version is immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end
$$
"""

DOCUMENTS_GUARD_TRIGGER = """
create trigger trg_tender_version_documents_guard
before insert or update or delete on tender_version_documents
for each row execute function tender_version_documents_guard()
"""


def upgrade() -> None:
    op.create_table(
        "tender_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("external_tender_id", sa.String(length=128), nullable=True),
        sa.Column("external_version", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "frozen", name="tender_version_status", native_enum=False, length=32),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_tender_versions_number_positive")),
        sa.CheckConstraint(
            "status <> 'frozen' or (manifest_sha256 is not null and frozen_at is not null)",
            name=op.f("ck_tender_versions_frozen_has_manifest"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name=op.f("fk_tender_versions_project_id_workspace_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_tender_versions_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_versions")),
        sa.UniqueConstraint("project_id", "number", name="uq_tender_versions_project_number"),
    )
    op.create_index(op.f("ix_tender_versions_created_at"), "tender_versions", ["created_at"])
    op.create_index(
        "uq_tender_versions_draft",
        "tender_versions",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )

    op.create_table(
        "tender_version_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tender_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_revision_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=True),
        sa.Column("use_in_model", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tender_version_id"],
            ["tender_versions.id"],
            name=op.f("fk_tender_version_documents_tender_version_id_tender_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_tender_version_documents_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_tender_version_documents_document_revision_id_document_revisions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_version_documents")),
        sa.UniqueConstraint(
            "tender_version_id", "document_id", name="uq_tender_version_documents_version_document"
        ),
    )
    op.create_index(
        "ix_tender_version_documents_document_revision_id",
        "tender_version_documents",
        ["document_revision_id"],
    )

    # asyncpg не принимает несколько команд в одном подготовленном запросе.
    for statement in (
        VERSION_GUARD_FUNCTION,
        VERSION_GUARD_TRIGGER,
        DOCUMENTS_GUARD_FUNCTION,
        DOCUMENTS_GUARD_TRIGGER,
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "drop trigger if exists trg_tender_version_documents_guard on tender_version_documents"
    )
    op.execute("drop trigger if exists trg_tender_versions_guard on tender_versions")
    op.execute("drop function if exists tender_version_documents_guard()")
    op.execute("drop function if exists tender_versions_guard()")

    op.drop_index(
        "ix_tender_version_documents_document_revision_id", table_name="tender_version_documents"
    )
    op.drop_table("tender_version_documents")
    op.drop_index("uq_tender_versions_draft", table_name="tender_versions")
    op.drop_index(op.f("ix_tender_versions_created_at"), table_name="tender_versions")
    op.drop_table("tender_versions")
