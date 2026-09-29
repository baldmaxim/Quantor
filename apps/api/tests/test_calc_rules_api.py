"""Реестр правил через HTTP и слой хранения (ADR-0030, PROMPT 03).

Черновик, утверждение вторым человеком, новая версия, вывод прежней из действия, отклонение;
неизменяемость утверждённой версии не только в API, но и при прямой записи в базу; черновик
из правила старого портала без изменения карантина; разбор опасностей; права, арендатор,
флаг; независимость от реестра фактов.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.contracts.calc.enums import CalcRuleStatus
from app.contracts.calc.rules import CalcRuleContent
from app.domain import AuditAction, OverrideScope, Role
from app.models import (
    AuditEvent,
    CalcFact,
    CalcRuleDefinition,
    CalcRuleReview,
    CalcRuleVersion,
    CalcSource,
    FeatureFlagOverride,
    UserIdentity,
    Workspace,
)
from app.services import projects as projects_service
from app.services.calc.rules.legacy import load_catalog, read_packaged_text
from app.services.calc.rules.validation import content_sha256
from tests.calc_rule_fixtures import (
    decision_source,
    engineering_source,
    geometry_content,
    normative_source,
)
from tests.conftest import make_context

API = "/api/v1/calc"
KEY = "test.riser.length"


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты реестра правил",
        )
    )
    await db_session.commit()


def _as(role: Role, workspace_id: uuid.UUID, user_id: uuid.UUID | None = None) -> AuthContext:
    if user_id is None:
        return make_context(role, workspace_id=workspace_id)
    return make_context(role, workspace_id=workspace_id, user_id=user_id)


APPROVE: dict[str, Any] = {"comment": "Проверено по тестовой фикстуре.", "legacy_review": []}


async def _create(client: AsyncClient, key: str = KEY, **content: Any) -> dict[str, Any]:
    response = await client.post(
        f"{API}/rules", json={"rule_key": key, "content": geometry_content(**content)}
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def _approve(
    client: AsyncClient, version: int, key: str = KEY, body: dict[str, Any] | None = None
) -> Any:
    return await client.post(f"{API}/rules/{key}/versions/{version}/approve", json=body or APPROVE)


# ------------------------------------------------------------------------------ флаг, права


class TestAccess:
    async def test_t17_closed_by_default(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            rules = await client.get(f"{API}/rules")
            legacy = await client.get(f"{API}/legacy-rules")
        assert rules.status_code == legacy.status_code == 403
        assert rules.json()["detail"]["code"] == "FEATURE_DISABLED"

    @pytest.mark.usefixtures("calc_enabled")
    async def test_roles(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        body = {"rule_key": KEY, "content": geometry_content()}
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            viewer_list = await client.get(f"{API}/rules")
            viewer_create = await client.post(f"{API}/rules", json=body)
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            reviewer_create = await client.post(f"{API}/rules", json=body)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            viewer_approve = await _approve(client, 1)
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            reviewer_approve = await _approve(client, 1)
        assert viewer_list.status_code == 200
        assert viewer_create.status_code == reviewer_create.status_code == 403
        assert viewer_approve.status_code == 403
        assert reviewer_approve.status_code == 200, reviewer_approve.text

    @pytest.mark.usefixtures("calc_enabled")
    async def test_workspace_boundary(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
        async with build_api(_as(Role.ENGINEER, second_workspace.id)) as client:
            foreign = await client.get(f"{API}/rules/{KEY}")
            listed = await client.get(f"{API}/rules")
            own = await client.post(
                f"{API}/rules", json={"rule_key": KEY, "content": geometry_content()}
            )
        assert foreign.status_code == 404
        assert listed.json() == []
        assert own.status_code == 201


# ------------------------------------------------------------------------ жизненный цикл


@pytest.mark.usefixtures("calc_enabled")
class TestLifecycle:
    async def test_t01_draft_is_created_and_not_eligible(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            draft = await _create(client)
            listed = (await client.get(f"{API}/rules")).json()
            taken = await client.post(
                f"{API}/rules", json={"rule_key": KEY, "content": geometry_content()}
            )
        assert (draft["version"], draft["status"]) == (1, "DRAFT")
        assert draft["calculation_eligible"] is False
        assert len(draft["content_sha256"]) == 64
        assert listed[0]["calculation_eligible"] is False
        assert listed[0]["approved_version"] is None
        assert taken.status_code == 409
        assert taken.json()["detail"]["code"] == "CALC_RULE_KEY_TAKEN"

    async def test_t07_t08_t09_versions(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        """Утверждённая v1 не правится; изменение — v2; после утверждения v2 v1 устарела,
        но читается по номеру с тем же содержанием и отпечатком."""
        engineer = _as(Role.ENGINEER, workspace_id)
        reviewer = _as(Role.REVIEWER, workspace_id, other_user.id)
        async with build_api(engineer) as client:
            await _create(client)
        async with build_api(reviewer) as client:
            v1 = (await _approve(client, 1)).json()
        assert (v1["status"], v1["calculation_eligible"]) == ("APPROVED", True)
        assert v1["approved_by"] == str(other_user.id)
        assert v1["reviews"][0]["from_status"] == "DRAFT"

        changed = geometry_content()
        changed["parameters"][0]["value"] = "0.7"
        async with build_api(engineer) as client:
            in_place = await client.put(f"{API}/rules/{KEY}/versions/1", json={"content": changed})
            v2 = await client.post(
                f"{API}/rules/{KEY}/versions",
                json={"change_reason": "Запас уточнён по тестовой фикстуре.", "content": changed},
            )
            second_draft = await client.post(
                f"{API}/rules/{KEY}/versions", json={"change_reason": "Ещё одна правка."}
            )
        assert in_place.status_code == 409
        assert in_place.json()["detail"]["code"] == "CALC_RULE_NOT_DRAFT"
        assert v2.status_code == 201, v2.text
        assert (v2.json()["version"], v2.json()["status"]) == (2, "DRAFT")
        assert v2.json()["content_sha256"] != v1["content_sha256"]
        assert second_draft.json()["detail"]["code"] == "CALC_RULE_DRAFT_EXISTS"

        async with build_api(reviewer) as client:
            approved = await _approve(client, 2)
            old = (await client.get(f"{API}/rules/{KEY}/versions/1")).json()
            rule = (await client.get(f"{API}/rules/{KEY}")).json()
            listed = (await client.get(f"{API}/rules")).json()
        assert approved.status_code == 200, approved.text
        assert old["status"] == "DEPRECATED"
        assert old["calculation_eligible"] is False
        assert old["content"] == v1["content"]
        assert old["content_sha256"] == v1["content_sha256"]
        # Отпечаток воспроизводится из содержания: по нему запуск докажет, какой редакцией жил.
        assert (
            content_sha256(CalcRuleContent.model_validate(old["content"]))
            == (old["content_sha256"])
        )
        assert old["deprecation_reason"] == "Заменена утверждённой версией 2"
        assert [item["to_status"] for item in old["reviews"]] == ["APPROVED", "DEPRECATED"]
        assert [item["version"] for item in rule["versions"]] == [1, 2]
        assert listed[0]["approved_version"] == 2
        assert listed[0]["calculation_eligible"] is True

        actions = set((await db_session.scalars(select(AuditEvent.action))).all())
        assert {
            AuditAction.CALC_RULE_CREATED.value,
            AuditAction.CALC_RULE_APPROVED.value,
            AuditAction.CALC_RULE_VERSION_CREATED.value,
            AuditAction.CALC_RULE_DEPRECATED.value,
        } <= actions

    async def test_author_cannot_approve_own_version(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
            response = await _approve(client, 1)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CALC_RULE_SELF_APPROVAL"

    async def test_editor_cannot_approve_own_edit(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        """Инженер поправил чужой черновик — утверждает уже третий человек, не он."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
        async with build_api(_as(Role.ENGINEER, workspace_id, other_user.id)) as client:
            edited = await client.put(
                f"{API}/rules/{KEY}/versions/1",
                json={"content": geometry_content(formula="L = h × n + запас")},
            )
            response = await _approve(client, 1)
        assert edited.json()["edited_by"] == str(other_user.id)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CALC_RULE_SELF_APPROVAL"

    async def test_reject_and_deprecate(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        decision = {"comment": "Основание не подтверждено."}
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
            await _create(client, "test.riser.other")
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            rejected = await client.post(f"{API}/rules/{KEY}/versions/1/reject", json=decision)
            approve_rejected = await _approve(client, 1)
            deprecate_draft = await client.post(
                f"{API}/rules/test.riser.other/versions/1/deprecate", json=decision
            )
            await _approve(client, 1, "test.riser.other")
            deprecated = await client.post(
                f"{API}/rules/test.riser.other/versions/1/deprecate", json=decision
            )
            by_status = (await client.get(f"{API}/rules", params={"status": "REJECTED"})).json()
        assert rejected.json()["status"] == "REJECTED"
        assert rejected.json()["rejection_reason"] == decision["comment"]
        assert approve_rejected.json()["detail"]["code"] == "CALC_RULE_TRANSITION_INVALID"
        assert deprecate_draft.json()["detail"]["code"] == "CALC_RULE_TRANSITION_INVALID"
        assert deprecated.json()["status"] == "DEPRECATED"
        assert deprecated.json()["calculation_eligible"] is False
        assert [item["rule_key"] for item in by_status] == [KEY]

    async def test_filters(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
            await _create(client, "test.tender.reserve", rule_type="TENDER_ASSUMPTION")
            tender = (
                await client.get(f"{API}/rules", params={"rule_type": "TENDER_ASSUMPTION"})
            ).json()
            by_system = (await client.get(f"{API}/rules", params={"system": "в1"})).json()
            other_system = (await client.get(f"{API}/rules", params={"system": "К1"})).json()
        assert [item["rule_key"] for item in tender] == ["test.tender.reserve"]
        assert tender[0]["notice"] == (
            "Это не норматив и не факт документации. Это тендерное допущение."
        )
        assert len(by_system) == 2
        assert other_system == []


# ----------------------------------------------------------------- основание утверждения


@pytest.mark.usefixtures("calc_enabled")
class TestApprovalBasis:
    async def test_t04_normative_without_document_is_blocked(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client, rule_type="NORMATIVE")
            await _create(
                client, "test.riser.normative", rule_type="NORMATIVE", sources=[normative_source()]
            )
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            blocked = await _approve(client, 1)
            approved = await _approve(client, 1, "test.riser.normative")
        assert blocked.status_code == 422
        assert blocked.json()["detail"]["code"] == "CALC_RULE_APPROVAL_BLOCKED"
        assert "нормативного документа" in blocked.json()["detail"]["message"]
        assert approved.status_code == 200, approved.text
        assert approved.json()["content"]["sources"][0]["designation"] == "ТЕСТ 00.00000.0000"

    async def test_t10_t11_t16_content_is_checked_on_save(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        wrong_unit = geometry_content()
        wrong_unit["inputs"][0]["unit"] = "kPa"
        with_code = {**geometry_content(), "code": "eval('1')"}
        vor = geometry_content(sources=[decision_source(basis="Так в ВОР Заказчика")])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            unit = await client.post(f"{API}/rules", json={"rule_key": KEY, "content": wrong_unit})
            code = await client.post(f"{API}/rules", json={"rule_key": KEY, "content": with_code})
            from_vor = await client.post(f"{API}/rules", json={"rule_key": KEY, "content": vor})
            status_field = await client.post(
                f"{API}/rules",
                json={"rule_key": KEY, "content": geometry_content(), "status": "APPROVED"},
            )
            listed = (await client.get(f"{API}/rules")).json()
        assert unit.json()["detail"]["code"] == "CALC_RULE_CONTENT_INVALID"
        assert code.status_code == 422
        assert from_vor.json()["detail"]["code"] == "CALC_RULE_CONTENT_INVALID"
        assert "ВОР Заказчика" in from_vor.json()["detail"]["message"]
        # Статус не задаётся запросом: черновик становится утверждённым только утверждением.
        assert status_field.status_code == 422
        assert listed == []

    async def test_tender_assumption_approval_needs_decision(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        scope = {**geometry_content()["applicability"], "limitations": ["только стадия П"]}
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(
                client,
                rule_type="TENDER_ASSUMPTION",
                applicability=scope,
                impact="Длина больше на 10 %.",
                sources=[engineering_source()],
            )
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            blocked = await _approve(client, 1)
        assert "решения ответственного лица" in blocked.json()["detail"]["message"]


# ----------------------------------------------------------- неизменяемость в базе (T19, T20)


async def _approved_version(
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    key: str = KEY,
) -> None:
    async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
        await _create(client, key)
    async with build_api(_as(Role.REVIEWER, workspace_id, reviewer_id)) as client:
        response = await _approve(client, 1, key)
    assert response.status_code == 200, response.text


async def _row(session: AsyncSession, key: str = KEY, version: int = 1) -> CalcRuleVersion:
    row = await session.scalar(
        select(CalcRuleVersion)
        .join(CalcRuleDefinition)
        .where(CalcRuleDefinition.rule_key == key, CalcRuleVersion.version == version)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


@pytest.mark.usefixtures("calc_enabled")
class TestPersistenceGuard:
    async def test_t19_orm_cannot_change_approved_content(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        await _approved_version(build_api, workspace_id, other_user.id)
        for change in (
            {"formula_text": "L = 2 × h"},
            {"parameters": [{"name": "reserve", "value": "9", "unit": "m", "description": "x"}]},
            {"implementation_key": "test.other.v1"},
            {"applicability": {"systems": ["К1"]}},
            {"sources": []},
            {"content_sha256": "0" * 64},
            {"status": CalcRuleStatus.DRAFT, "approved_at": None, "approved_by": None},
        ):
            row = await _row(db_session)
            for name, value in change.items():
                setattr(row, name, value)
            with pytest.raises(DBAPIError, match=r"immutable|not allowed"):
                await db_session.flush()
            await db_session.rollback()

        row = await _row(db_session)
        assert row.formula_text == "L = h × n + reserve"
        assert row.status.value == "APPROVED"

    async def test_t19_direct_sql_cannot_change_approved_content(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        await _approved_version(build_api, workspace_id, other_user.id)
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.execute(
                update(CalcRuleVersion)
                .values(title="Подменено")
                .execution_options(synchronize_session=False)
            )
        await db_session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                update(CalcRuleDefinition)
                .values(rule_key="test.other.key")
                .execution_options(synchronize_session=False)
            )
        await db_session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                update(CalcRuleReview)
                .values(comment="Подменено")
                .execution_options(synchronize_session=False)
            )
        await db_session.rollback()

    async def test_deprecated_version_is_frozen_but_deprecation_is_allowed(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        await _approved_version(build_api, workspace_id, other_user.id)
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            response = await client.post(
                f"{API}/rules/{KEY}/versions/1/deprecate", json={"comment": "Выведено в тесте."}
            )
        assert response.status_code == 200, response.text
        row = await _row(db_session)
        row.deprecation_reason = "Переписано задним числом"
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.flush()
        await db_session.rollback()

    async def test_t20_decided_versions_cannot_disappear(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        await _approved_version(build_api, workspace_id, other_user.id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await client.post(
                f"{API}/rules/{KEY}/versions", json={"change_reason": "Новая редакция в тесте."}
            )
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            await _approve(client, 2)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client, "test.riser.rejected")
            await client.post(
                f"{API}/rules/test.riser.rejected/versions/1/reject",
                json={"comment": "Отклонено в тесте."},
            )
        # v1 устарела, v2 утверждена, другое правило отклонено — ни одну не удалить.
        for key, version in ((KEY, 1), (KEY, 2), ("test.riser.rejected", 1)):
            row = await _row(db_session, key, version)
            await db_session.delete(row)
            with pytest.raises(DBAPIError, match="cannot be deleted"):
                await db_session.flush()
            await db_session.rollback()
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            await db_session.execute(delete(CalcRuleVersion))
        await db_session.rollback()
        with pytest.raises(IntegrityError):
            await db_session.execute(delete(CalcRuleDefinition))
        await db_session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(delete(CalcRuleReview))
        await db_session.rollback()
        count = await db_session.scalar(select(func.count()).select_from(CalcRuleVersion))
        assert count == 3

    async def test_t03_legacy_status_is_not_storable(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Таблица версий не принимает UNVERIFIED_LEGACY: старые правила — только в карантине."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _create(client)
        with pytest.raises(IntegrityError, match="own_statuses"):
            await db_session.execute(
                text(
                    "insert into calc_rule_versions (id, rule_id, version, status, rule_type,"
                    " title, description, formula_text, explanation, outputs, applicability,"
                    " content_sha256)"
                    " select gen_random_uuid(), rule_id, 2, 'UNVERIFIED_LEGACY', rule_type,"
                    " title, description, formula_text, explanation, outputs, applicability,"
                    " content_sha256 from calc_rule_versions"
                )
            )
        await db_session.rollback()
        # И переход черновика в карантинный статус запрещён триггером.
        with pytest.raises(DBAPIError, match="not allowed"):
            await db_session.execute(
                text("update calc_rule_versions set status = 'UNVERIFIED_LEGACY'")
            )
        await db_session.rollback()


# ------------------------------------------------------------- старый портал (T03, T21, T22)


def _from_legacy_body(key: str = "test.floor.height_rule", **extra: Any) -> dict[str, Any]:
    content = geometry_content()
    return {
        "rule_key": key,
        "rule_type": "GEOMETRY",
        "discipline": "VK",
        "applicability": content["applicability"],
        "outputs": content["outputs"],
        **extra,
    }


@pytest.mark.usefixtures("calc_enabled")
class TestLegacy:
    async def test_quarantine_is_read_only(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.PLATFORM_ADMIN, workspace_id)) as client:
            catalog = (await client.get(f"{API}/legacy-rules")).json()
            one = (await client.get(f"{API}/legacy-rules/LEG-VK-001")).json()
            missing = await client.get(f"{API}/legacy-rules/LEG-VK-999")
            attempts = [
                await client.put(f"{API}/legacy-rules/LEG-VK-001", json={"status": "APPROVED"}),
                await client.patch(f"{API}/legacy-rules/LEG-VK-001", json={"status": "APPROVED"}),
                await client.delete(f"{API}/legacy-rules/LEG-VK-001"),
                await client.post(f"{API}/legacy-rules/LEG-VK-001/approve", json=APPROVE),
                await client.post(f"{API}/legacy-rules/LEG-VK-001/deprecate", json=APPROVE),
                await client.post(f"{API}/rules/LEG-VK-001/versions/1/approve", json=APPROVE),
            ]
        assert catalog["entry_count"] == len(catalog["items"]) == 365
        assert {item["status"] for item in catalog["items"]} == {"UNVERIFIED_LEGACY"}
        assert not any(item["calculation_eligible"] for item in catalog["items"])
        assert one["notice"] == "НЕ ПРОВЕРЕНО / НЕ ИСПОЛЬЗУЕТСЯ В РАСЧЁТЕ"
        assert missing.status_code == 404
        assert all(item.status_code in {404, 405} for item in attempts), [
            item.status_code for item in attempts
        ]

    async def test_t21_draft_from_legacy_leaves_quarantine_unchanged(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        packaged = hashlib.sha256(read_packaged_text().encode()).hexdigest()
        entry = load_catalog().get("LEG-VK-001")
        assert entry is not None
        before = entry.model_dump()

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(
                f"{API}/legacy-rules/LEG-VK-001/drafts", json=_from_legacy_body()
            )
            after_api = (await client.get(f"{API}/legacy-rules/LEG-VK-001")).json()
        assert response.status_code == 201, response.text
        draft = response.json()
        assert (draft["rule_key"], draft["version"], draft["status"]) == (
            "test.floor.height_rule",
            1,
            "DRAFT",
        )
        assert draft["calculation_eligible"] is False
        assert draft["content"]["implementation_key"] is None
        assert draft["content"]["sources"] == [
            {
                "kind": "LEGACY_CODE",
                "legacy_ids": ["LEG-VK-001"],
                "note": (
                    "Место в старом коде: main.js:351-353 (getHeights); "
                    "state.js:9-10, 102-103, 171-172, 213-214; index.html:2381-2386. "
                    f"Запись разбора: {entry.location}"
                ),
            }
        ]
        [provenance] = draft["legacy_provenance"]
        assert provenance["legacy_id"] == "LEG-VK-001"
        assert provenance["hazards"] == ["HIDDEN_DEFAULT"]
        assert provenance["catalog_version"] == "calc.legacy_catalog.v1"

        # Карантин не изменился ни в памяти, ни в пакете, ни в ответе API.
        assert entry.model_dump() == before
        assert hashlib.sha256(read_packaged_text().encode()).hexdigest() == packaged
        assert after_api["status"] == "UNVERIFIED_LEGACY"
        assert after_api["calculation_eligible"] is False
        rules = await db_session.scalar(select(func.count()).select_from(CalcRuleDefinition))
        assert rules == 1

        # Черновик из старого правила не утверждается сам собой (T03).
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            blocked = await _approve(client, 1, "test.floor.height_rule")
        message = blocked.json()["detail"]["message"]
        assert blocked.status_code == 422
        assert "implementation_key" in message
        assert "нет основания" in message
        assert "LEG-VK-001: нет разбора" in message

        # Ссылку на старое правило правкой не убрать: иначе пропал бы и обязательный разбор.
        without_legacy = {**draft["content"], "sources": geometry_content()["sources"]}
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            edited = await client.put(
                f"{API}/rules/test.floor.height_rule/versions/1",
                json={"content": without_legacy},
            )
        assert edited.status_code == 422, edited.text
        assert "LEG-VK-001" in edited.json()["detail"]["message"]

    async def test_out_of_scope_legacy_is_not_a_draft(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(
                f"{API}/legacy-rules/LEG-EST-024/drafts", json=_from_legacy_body()
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "CALC_LEGACY_OUT_OF_SCOPE"

    async def test_t22_hazards_block_approval_until_each_is_resolved(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        """Двойное умножение старого портала: утверждение только с итогом по каждой опасности."""
        key = "test.ov.valves"
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            created = await client.post(
                f"{API}/legacy-rules/LEG-OV-037/drafts",
                json=_from_legacy_body(key, discipline="VK"),
            )
            assert created.status_code == 201, created.text
            draft = created.json()["content"]
            scope = {**draft["applicability"], "limitations": ["только тестовое здание"]}
            fixed = {
                **geometry_content(),
                "rule_type": "ENGINEERING",
                "applicability": scope,
                "sources": [engineering_source(), *draft["sources"]],
            }
            updated = await client.put(f"{API}/rules/{key}/versions/1", json={"content": fixed})
        assert updated.status_code == 200, updated.text
        hazards = updated.json()["legacy_provenance"][0]["hazards"]
        assert set(hazards) == {"DOUBLE_MULTIPLICATION", "DEFECT"}

        def review(**outcomes: str) -> dict[str, Any]:
            return {
                "comment": "Проверено по тестовой методике.",
                "legacy_review": [
                    {
                        "legacy_id": "LEG-OV-037",
                        "resolution": "Число клапанов считается по системам один раз.",
                        "hazards": [
                            {"hazard": hazard, "outcome": outcome, "comment": "Проверено."}
                            for hazard, outcome in outcomes.items()
                        ],
                    }
                ],
            }

        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            none = await _approve(client, 1, key)
            partial = await _approve(client, 1, key, review(DOUBLE_MULTIPLICATION="FIXED"))
            confirmed = await _approve(
                client, 1, key, review(DOUBLE_MULTIPLICATION="REJECTED", DEFECT="FIXED")
            )
            approved = await _approve(
                client, 1, key, review(DOUBLE_MULTIPLICATION="FIXED", DEFECT="NOT_APPLICABLE")
            )
        assert "нет разбора" in none.json()["detail"]["message"]
        assert "DEFECT" in partial.json()["detail"]["message"]
        assert "подтверждена и не устранена" in confirmed.json()["detail"]["message"]
        assert approved.status_code == 200, approved.text
        [decision] = approved.json()["reviews"]
        outcomes = {
            item["hazard"]: item["outcome"] for item in decision["legacy_review"][0]["hazards"]
        }
        assert outcomes == {"DOUBLE_MULTIPLICATION": "FIXED", "DEFECT": "NOT_APPLICABLE"}
        stored = await db_session.scalar(select(CalcRuleReview.legacy_review))
        assert stored is not None and stored[0]["hazards"][0]["comment"] == "Проверено."


# --------------------------------------------------------------------- реестр фактов (T15)


@pytest.mark.usefixtures("calc_enabled")
async def test_t15_rules_do_not_touch_facts(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    other_user: UserIdentity,
) -> None:
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="ЖК"
    )
    await db_session.commit()
    async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
        source = (
            await client.post(
                f"{API}/projects/{project.id}/sources",
                json={"source_class": "MANUAL", "title": "Инженер"},
            )
        ).json()
        fact = await client.post(
            f"{API}/projects/{project.id}/facts",
            json={
                "source_id": source["id"],
                "fact_type": "floor.height",
                "subject": {"building": "1", "floor": "2"},
                "value": {"kind": "NUMBER", "value": "3.3", "unit": "m"},
                "method": "MANUAL",
                "note": "по листу проекта",
            },
        )
        assert fact.status_code == 201, fact.text

    async def snapshot() -> list[tuple[Any, ...]]:
        facts = (await db_session.execute(select(CalcFact).order_by(CalcFact.id))).scalars()
        sources = await db_session.scalar(select(func.count()).select_from(CalcSource))
        return [
            (item.id, item.status, item.review_status, item.value, item.version) for item in facts
        ] + [("sources", sources)]

    before = await snapshot()
    await _approved_version(build_api, workspace_id, other_user.id)
    async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
        await client.post(f"{API}/legacy-rules/LEG-VK-001/drafts", json=_from_legacy_body())
        await client.post(f"{API}/rules/{KEY}/versions", json={"change_reason": "Правка."})
    db_session.expire_all()
    assert await snapshot() == before
