"""Явная область видимости задания: арендатор принадлежит самому заданию

Revision ID: 0007_job_workspace_scope
Revises: 0006_job_worker_lease
Create Date: 2026-09-08

До этой ревизии принадлежность задания арендатору выводилась джойном через проект, а
задание с пустым `project_id` считалось общесистемным и было видно из **любого** рабочего
пространства. Общесистемных заданий пока никто не создавал, поэтому утечки данных не
произошло, но Stage 2A вводит новые типы заданий — чинить надо до них, а не после.

Область видимости кодируется парой колонок, без отдельного дискриминатора: он был бы
производным от той же пары и однажды разошёлся бы с ней.

    workspace_id | project_id | смысл
    NOT NULL     | NULL       | задание пространства
    NOT NULL     | NOT NULL   | задание проекта
    NULL         | NULL       | общесистемное
    NULL         | NOT NULL   | непредставимо — запрещено CHECK

`workspace_id` намеренно остаётся nullable: NULL здесь не «неизвестно», а «вне арендаторов».
Инвариант держит CHECK, а не nullability.

Одноколоночный внешний ключ на `projects` заменён составным на пару `(id, workspace_id)`:
именно он гарантирует, что арендатор задания совпадает с арендатором его проекта. Проверка
в сервисе даёт понятную ошибку, но не удержит запись мимо API — например, эту же миграцию.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_job_workspace_scope"
down_revision: str | None = "0006_job_worker_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Колонка добавляется nullable и без умолчания: так это операция над метаданными,
    # без переписывания таблицы.
    op.add_column("jobs", sa.Column("workspace_id", sa.Uuid(), nullable=True))

    # Единственный источник правды о принадлежности задания на сегодня — его проект,
    # через который она и выводилась джойном.
    op.execute(
        """
        update jobs
           set workspace_id = projects.workspace_id
          from projects
         where jobs.project_id = projects.id
        """
    )

    # Строк без проекта быть не должно, но миграция обязана быть безопасной. Такие строки
    # остаются с пустым `workspace_id`, то есть становятся общесистемными: когда
    # принадлежность неизвестна, единственный безопасный исход — отказ в доступе, а не
    # выдача его наугад. Количество печатается, чтобы факт не прошёл незамеченным.
    orphans = (
        op.get_bind()
        .execute(sa.text("select count(*) from jobs where workspace_id is null"))
        .scalar_one()
    )
    if orphans:
        print(f"[0007] заданий без проекта переведено в общесистемные: {orphans}")

    # Констрейнты — только после backfill: до него CHECK упал бы на живых данных.
    op.create_check_constraint(
        "workspace_scope", "jobs", "project_id is null or workspace_id is not null"
    )

    # Цель составного внешнего ключа. По данным избыточно (`id` — первичный ключ), но
    # PostgreSQL требует объявленной уникальности ровно на том наборе колонок.
    op.create_unique_constraint("uq_projects_id_workspace", "projects", ["id", "workspace_id"])

    # Два внешних ключа на одну таблицу дали бы два каскадных пути и неоднозначное условие
    # соединения в relationship, поэтому старый снимается, а не остаётся рядом.
    op.drop_constraint("fk_jobs_project_id_projects", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "fk_jobs_project_id_workspace_id_projects",
        "jobs",
        "projects",
        ["project_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "fk_jobs_workspace_id_workspaces",
        "jobs",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Индекс последним: строится по уже заполненной колонке.
    op.create_index("ix_jobs_workspace_id_created_at", "jobs", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_workspace_id_created_at", table_name="jobs")
    op.drop_constraint("fk_jobs_workspace_id_workspaces", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_project_id_workspace_id_projects", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "fk_jobs_project_id_projects",
        "jobs",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_projects_id_workspace", "projects", type_="unique")
    # op.f — имя уже финальное; без него naming convention снова допишет ck_jobs_…
    op.drop_constraint(op.f("ck_jobs_workspace_scope"), "jobs", type_="check")
    op.drop_column("jobs", "workspace_id")
