"""Версия тендера: замороженный комплект ревизий (ADR-0035, этап M2).

Сеть не используется: клиент HUBTender подменяется транспортом, как в `test_api_tenderhub.py`.
Триггеры базы проверяются прямым SQL мимо сервиса — именно там живёт неизменяемость.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_optional_tenderhub_client, get_tenderhub_client
from app.auth.context import AuthContext
from app.core.config import Settings
from app.domain import (
    DocumentKind,
    OverrideScope,
    ProcessingStatus,
    ProjectSource,
    Role,
)
from app.errors import DomainError, ErrorCode
from app.integrations.tenderhub import TenderHubClient
from app.models import (
    AuditEvent,
    Document,
    DocumentRevision,
    FeatureFlagOverride,
    Project,
    Workspace,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.tender_versions import ManifestEntry, compute_manifest_sha256
from app.storage.keys import revision_key
from tests.conftest import FakeObjectStorage, _build_api, clean_settings, make_context

NUMBER = "ТН-0042"
HUB_ID = "11111111-1111-4111-8111-111111111111"
HUB_ID_V2 = "22222222-2222-4222-8222-222222222222"
BASE = "/api/v1/projects/{project}/tender-versions"


def hub_tender(tender_id: str, *, number: str | None = NUMBER, version: int = 1) -> dict[str, Any]:
    return {
        "id": tender_id,
        "tender_number": number,
        "title": "ЖК «Северный»",
        "client_name": "ООО «Заказчик»",
        "version": version,
        "is_archived": False,
        "submission_deadline": "2026-12-01",
    }


def hub_handler(rows: dict[str, dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    """Подмена TenderHUB: обзор тендера по идентификатору и список с нестрогим поиском."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/overview"):
            tender = rows.get(path.split("/")[-2])
            if tender is None:
                return httpx.Response(404, json={"code": "NOT_FOUND"})
            return httpx.Response(200, json={"data": tender})
        search = request.url.params.get("search", "")
        found = [row for row in rows.values() if search in str(row["tender_number"])]
        return httpx.Response(200, json={"data": found})

    return handler


def hub_client(handler: Callable[[httpx.Request], httpx.Response]) -> TenderHubClient:
    return TenderHubClient(
        Settings(tenderhub_api_token="thk_test_key"),
        transport=httpx.MockTransport(handler),
    )


def refuse(_: httpx.Request) -> httpx.Response:
    raise AssertionError("тест не должен обращаться к HUBTender")


@pytest.fixture
async def versions_enabled(db_session: AsyncSession) -> None:
    """Пилот включён для всей установки: проверяется предметная логика, не сам флаг."""
    db_session.add(
        FeatureFlagOverride(
            flag_key="tender.versions",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты версий тендера",
        )
    )
    await db_session.commit()


@pytest.fixture
def portal(
    db_session: AsyncSession, fake_storage: FakeObjectStorage, versions_enabled: None
) -> Iterator[Callable[..., AsyncClient]]:
    """Фабрика клиентов: HUBTender подменён (по умолчанию к нему обращаться нельзя)."""
    apps: list[Any] = []

    def make(
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
        *,
        context: AuthContext | None = None,
        integration_off: bool = False,
    ) -> AsyncClient:
        app, client = _build_api(db_session, fake_storage, context=context or make_context())

        async def override() -> AsyncIterator[TenderHubClient | None]:
            if integration_off:
                yield None
                return
            async with hub_client(handler or refuse) as hub:
                yield hub

        app.dependency_overrides[get_optional_tenderhub_client] = override
        apps.append(app)
        return client

    try:
        yield make
    finally:
        for app in apps:
            app.dependency_overrides.clear()


# ------------------------------------------------------------------------- данные


async def make_project(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    hub: bool = False,
    number: str = NUMBER,
    external_id: str = HUB_ID,
) -> Project:
    project = await projects_service.create_project(
        session,
        workspace_id=workspace_id,
        name="Проект",
        source=ProjectSource.TENDERHUB if hub else ProjectSource.MANUAL,
        external_id=external_id if hub else None,
        external_ref=number if hub else None,
    )
    await session.commit()
    return project


async def make_revision(
    session: AsyncSession, document: Document, label: str, *, sha256: str | None = None
) -> DocumentRevision:
    revision_id = uuid.uuid4()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=revision_id,
        source_filename=f"{label}.pdf",
        source_mime="application/pdf",
        source_size=10,
        source_sha256=sha256 or hashlib.sha256(f"{document.id}-{label}".encode()).hexdigest(),
        storage_key=revision_key(revision_id, f"{label}.pdf"),
        processing_status=ProcessingStatus.UNPROCESSED,
    )
    # Отдельная транзакция на ревизию: `now()` внутри транзакции постоянен, и две ревизии
    # одной транзакции были бы неразличимы по времени создания.
    await session.commit()
    return revision


async def make_document(
    session: AsyncSession, project: Project, name: str, revisions: int = 1
) -> tuple[Document, list[DocumentRevision]]:
    document = await documents_service.create_document(
        session, project=project, display_name=name, document_kind=DocumentKind.PDF
    )
    await session.commit()
    return document, [
        await make_revision(session, document, f"{name}-{index}")
        for index in range(1, revisions + 1)
    ]


def url(project: Project, *tail: object) -> str:
    return "/".join([BASE.format(project=project.id), *map(str, tail)])


def error_code(response: httpx.Response) -> str:
    return str(response.json()["detail"]["code"])


# -------------------------------------------------------------------- отпечаток


def entry(
    document: int, *, sha: str = "a" * 64, section: str | None = "АР", use: bool = True
) -> ManifestEntry:
    return ManifestEntry(
        document_id=uuid.UUID(int=document),
        document_revision_id=uuid.UUID(int=document + 1000),
        source_sha256=sha,
        section=section,
        use_in_model=use,
    )


class TestManifest:
    def test_golden_value_is_canonical_json(self) -> None:
        """SHA-256 канонического JSON: ключи по алфавиту, без пробелов, кириллица как есть."""
        entries = [entry(2, section=None, use=False), entry(1)]

        canonical = (
            '{"documents":['
            f'{{"document_id":"{uuid.UUID(int=1)}","document_revision_id":"{uuid.UUID(int=1001)}",'
            f'"section":"АР","source_sha256":"{"a" * 64}","use_in_model":true}},'
            f'{{"document_id":"{uuid.UUID(int=2)}","document_revision_id":"{uuid.UUID(int=1002)}",'
            f'"section":null,"source_sha256":"{"a" * 64}","use_in_model":false}}'
            '],"external_version":3,"tender_number":"ТН-0042"}'
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        assert (
            compute_manifest_sha256(tender_number=NUMBER, external_version=3, entries=entries)
            == expected
        )

    def test_is_deterministic_and_ignores_input_order(self) -> None:
        entries = [entry(3), entry(1), entry(2)]

        first = compute_manifest_sha256(tender_number=NUMBER, external_version=1, entries=entries)
        second = compute_manifest_sha256(
            tender_number=NUMBER, external_version=1, entries=list(reversed(entries))
        )

        assert first == second
        assert len(first) == 64

    @pytest.mark.parametrize(
        "changed",
        [
            {"tender_number": "ТН-0043"},
            {"tender_number": None},
            {"external_version": 2},
            {"external_version": None},
            {"entries": [entry(1, sha="b" * 64)]},
            {"entries": [entry(1, section="КР")]},
            {"entries": [entry(1, section=None)]},
            {"entries": [entry(1, use=False)]},
            {"entries": [entry(1), entry(2)]},
        ],
    )
    def test_every_part_of_the_composition_changes_the_hash(self, changed: dict[str, Any]) -> None:
        base: dict[str, Any] = {
            "tender_number": NUMBER,
            "external_version": 1,
            "entries": [entry(1)],
        }

        assert compute_manifest_sha256(**base) != compute_manifest_sha256(**{**base, **changed})

    def test_revision_without_source_hash_is_refused(self) -> None:
        with pytest.raises(DomainError) as error:
            compute_manifest_sha256(
                tender_number=NUMBER, external_version=None, entries=[entry(1, sha="  ")]
            )

        assert error.value.code is ErrorCode.TENDER_VERSION_REVISION_NO_HASH


# ------------------------------------------------------------------------ API


class TestLifecycle:
    async def test_draft_is_filled_with_latest_revisions(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        first, first_revisions = await make_document(db_session, project, "АР", revisions=2)
        await make_document(db_session, project, "КР")

        async with portal() as api:
            response = await api.post(url(project), json={"label": "Первая"})

        assert response.status_code == 201
        body = response.json()
        assert body["number"] == 1
        assert body["status"] == "draft"
        assert body["manifest_sha256"] is None
        assert body["document_count"] == 2
        by_document = {row["document_id"]: row for row in body["documents"]}
        chosen = by_document[str(first.id)]
        assert chosen["document_revision_id"] == str(first_revisions[1].id)
        assert chosen["revision_number"] == 2
        assert chosen["source_sha256"] == first_revisions[1].source_sha256
        assert chosen["document_name"] == "АР"
        assert chosen["use_in_model"] is True
        assert chosen["section"] is None

    async def test_second_draft_is_a_conflict(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")

        async with portal() as api:
            first = await api.post(url(project), json={})
            second = await api.post(url(project), json={})

        assert first.status_code == 201
        assert second.status_code == 409
        assert error_code(second) == ErrorCode.TENDER_VERSION_DRAFT_EXISTS.value

    async def test_numbers_grow_per_project(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        other = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")

        async with portal() as api:
            first = (await api.post(url(project), json={})).json()
            assert (await api.post(url(project, first["id"], "freeze"))).status_code == 200
            second = (await api.post(url(project), json={})).json()
            elsewhere = (await api.post(url(other), json={})).json()
            listing = (await api.get(url(project))).json()

        assert (first["number"], second["number"], elsewhere["number"]) == (1, 2, 1)
        # Список — от новой версии к старой.
        assert [row["number"] for row in listing] == [2, 1]
        assert [row["status"] for row in listing] == ["draft", "frozen"]

    async def test_composition_is_edited_in_a_draft(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        document, revisions = await make_document(db_session, project, "АР", revisions=2)

        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            changed = await api.put(
                url(project, version["id"], "documents", document.id),
                json={
                    "document_revision_id": str(revisions[0].id),
                    "section": " АР ",
                    "use_in_model": False,
                },
            )
            removed = await api.delete(url(project, version["id"], "documents", document.id))
            missing = await api.delete(url(project, version["id"], "documents", document.id))
            readded = await api.put(
                url(project, version["id"], "documents", document.id),
                json={"document_revision_id": str(revisions[1].id)},
            )

        row = changed.json()["documents"][0]
        assert row["document_revision_id"] == str(revisions[0].id)
        assert row["revision_number"] == 1
        assert row["section"] == "АР"
        assert row["use_in_model"] is False
        assert removed.status_code == 204
        assert missing.status_code == 404
        assert readded.json()["documents"][0]["use_in_model"] is True

    async def test_foreign_revision_is_refused(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        document, [first_revision] = await make_document(db_session, project, "АР")
        _, same_project = await make_document(db_session, project, "КР")
        stranger = await make_project(db_session, second_workspace.id)
        foreign_document, foreign = await make_document(db_session, stranger, "Чужой")

        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            target = url(project, version["id"], "documents", document.id)
            other_document = await api.put(
                target, json={"document_revision_id": str(same_project[0].id)}
            )
            other_project = await api.put(target, json={"document_revision_id": str(foreign[0].id)})
            foreign_doc = await api.put(
                url(project, version["id"], "documents", foreign_document.id),
                json={"document_revision_id": str(foreign[0].id)},
            )
            unknown = await api.put(target, json={"document_revision_id": str(uuid.uuid4())})
            after = (await api.get(url(project, version["id"]))).json()

        for response in (other_document, other_project, unknown):
            assert response.status_code == 422, response.text
            assert error_code(response) == ErrorCode.TENDER_VERSION_REVISION_MISMATCH.value
        # Документ чужого проекта неотличим от несуществующего.
        assert foreign_doc.status_code == 404
        # Состав не тронут отказами.
        chosen = {row["document_id"]: row for row in after["documents"]}
        assert len(chosen) == 2
        assert chosen[str(document.id)]["document_revision_id"] == str(first_revision.id)

    async def test_freeze_fixes_the_manifest_and_closes_the_version(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)
        first, first_revisions = await make_document(db_session, project, "АР")
        second, second_revisions = await make_document(db_session, project, "КР")
        rows = {HUB_ID_V2: hub_tender(HUB_ID_V2, version=3)}

        async with portal(hub_handler(rows)) as api:
            version = (await api.post(url(project), json={"external_tender_id": HUB_ID_V2})).json()
            await api.put(
                url(project, version["id"], "documents", second.id),
                json={
                    "document_revision_id": str(second_revisions[0].id),
                    "section": "КР",
                    "use_in_model": False,
                },
            )
            frozen = await api.post(url(project, version["id"], "freeze"))
            again = await api.post(url(project, version["id"], "freeze"))
            patched = await api.patch(url(project, version["id"]), json={"label": "Поздно"})
            put = await api.put(
                url(project, version["id"], "documents", first.id),
                json={"document_revision_id": str(first_revisions[0].id)},
            )
            removed = await api.delete(url(project, version["id"], "documents", first.id))
            deleted = await api.delete(url(project, version["id"]))

        assert frozen.status_code == 200, frozen.text
        body = frozen.json()
        expected = compute_manifest_sha256(
            tender_number=NUMBER,
            external_version=3,
            entries=[
                ManifestEntry(
                    first.id, first_revisions[0].id, first_revisions[0].source_sha256, None, True
                ),
                ManifestEntry(
                    second.id,
                    second_revisions[0].id,
                    second_revisions[0].source_sha256,
                    "КР",
                    False,
                ),
            ],
        )
        assert body["status"] == "frozen"
        assert body["manifest_sha256"] == expected
        assert body["frozen_at"] is not None
        assert body["frozen_by"] is not None
        assert body["external_version"] == 3
        assert body["tender_number"] == NUMBER
        for response in (again, patched, put, removed, deleted):
            assert response.status_code == 409, response.text
            assert error_code(response) == ErrorCode.TENDER_VERSION_FROZEN.value

    async def test_empty_version_is_not_frozen(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)

        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            response = await api.post(url(project, version["id"], "freeze"))
            after = (await api.get(url(project, version["id"]))).json()

        assert response.status_code == 422
        assert error_code(response) == ErrorCode.TENDER_VERSION_EMPTY.value
        assert after["status"] == "draft"

    async def test_draft_can_be_deleted_with_its_composition(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")

        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            deleted = await api.delete(url(project, version["id"]))
            gone = await api.get(url(project, version["id"]))
            # Место черновика освободилось.
            again = await api.post(url(project), json={})

        assert deleted.status_code == 204
        assert gone.status_code == 404
        assert again.status_code == 201
        rows = await db_session.execute(text("select count(*) from tender_version_documents"))
        assert rows.scalar_one() == 1

    async def test_changes_are_audited(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        document, revisions = await make_document(db_session, project, "АР")

        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            await api.patch(url(project, version["id"]), json={"label": "A"})
            await api.put(
                url(project, version["id"], "documents", document.id),
                json={"document_revision_id": str(revisions[0].id)},
            )
            await api.delete(url(project, version["id"], "documents", document.id))
            await api.put(
                url(project, version["id"], "documents", document.id),
                json={"document_revision_id": str(revisions[0].id)},
            )
            frozen = (await api.post(url(project, version["id"], "freeze"))).json()

        events = (
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.resource_type == "tender_version")
                )
            )
            .scalars()
            .all()
        )
        actions = sorted(event.action for event in events)
        assert actions == sorted(
            [
                "tender_version_created",
                "tender_version_updated",
                "tender_version_document_set",
                "tender_version_document_removed",
                "tender_version_document_set",
                "tender_version_frozen",
            ]
        )
        freeze_event = next(event for event in events if event.action == "tender_version_frozen")
        assert freeze_event.after_summary is not None
        assert freeze_event.after_summary["manifest_sha256"] == frozen["manifest_sha256"]


class TestBoundaries:
    async def test_flag_closes_the_whole_router_on_the_server(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        version_id, document_id = uuid.uuid4(), uuid.uuid4()
        app, client = _build_api(
            db_session, fake_storage, context=make_context(), settings=clean_settings()
        )
        try:
            async with client as api:
                responses = [
                    await api.get(url(project)),
                    await api.get(url(project, "hub-candidates")),
                    await api.post(url(project), json={}),
                    await api.get(url(project, version_id)),
                    await api.patch(url(project, version_id), json={}),
                    await api.delete(url(project, version_id)),
                    await api.put(
                        url(project, version_id, "documents", document_id),
                        json={"document_revision_id": str(uuid.uuid4())},
                    ),
                    await api.delete(url(project, version_id, "documents", document_id)),
                    await api.post(url(project, version_id, "freeze")),
                ]
        finally:
            app.dependency_overrides.clear()

        for response in responses:
            assert response.status_code == 403, response.request.url
            assert error_code(response) == ErrorCode.FEATURE_DISABLED.value

    async def test_other_workspace_sees_nothing(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")
        async with portal() as owner:
            version = (await owner.post(url(project), json={})).json()

        stranger = make_context(Role.ENGINEER, workspace_id=second_workspace.id)
        async with portal(context=stranger) as api:
            responses = [
                await api.get(url(project)),
                await api.get(url(project, "hub-candidates")),
                await api.post(url(project), json={}),
                await api.get(url(project, version["id"])),
                await api.post(url(project, version["id"], "freeze")),
                await api.delete(url(project, version["id"])),
            ]

        for response in responses:
            assert response.status_code == 404, response.request.url

    async def test_version_of_another_project_is_not_reachable(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        other = await make_project(db_session, workspace_id)
        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            response = await api.get(url(other, version["id"]))

        assert response.status_code == 404

    async def test_viewer_reads_but_does_not_change(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")
        async with portal() as owner:
            version = (await owner.post(url(project), json={})).json()

        viewer = make_context(Role.VIEWER, workspace_id=workspace_id)
        async with portal(context=viewer) as api:
            read = await api.get(url(project, version["id"]))
            listing = await api.get(url(project))
            created = await api.post(url(project), json={})
            frozen = await api.post(url(project, version["id"], "freeze"))

        assert read.status_code == listing.status_code == 200
        assert created.status_code == frozen.status_code == 403


class TestHubLink:
    async def test_link_takes_version_from_hubtender(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)
        rows = {HUB_ID: hub_tender(HUB_ID, version=1), HUB_ID_V2: hub_tender(HUB_ID_V2, version=2)}

        async with portal(hub_handler(rows)) as api:
            version = (await api.post(url(project), json={})).json()
            linked = await api.patch(
                url(project, version["id"]), json={"external_tender_id": HUB_ID_V2}
            )
            label_only = await api.patch(url(project, version["id"]), json={"label": "Подпись"})
            unlinked = await api.patch(
                url(project, version["id"]), json={"external_tender_id": None}
            )

        assert version["external_tender_id"] is None
        assert linked.json()["external_tender_id"] == HUB_ID_V2
        assert linked.json()["external_version"] == 2
        # Присланная только подпись связь не трогает.
        assert label_only.json()["external_tender_id"] == HUB_ID_V2
        assert label_only.json()["label"] == "Подпись"
        assert unlinked.json()["external_tender_id"] is None
        assert unlinked.json()["external_version"] is None

    async def test_other_tender_number_is_refused(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)
        rows = {HUB_ID_V2: hub_tender(HUB_ID_V2, number="ТН-0099", version=2)}

        async with portal(hub_handler(rows)) as api:
            created = await api.post(url(project), json={"external_tender_id": HUB_ID_V2})
            version = (await api.post(url(project), json={})).json()
            patched = await api.patch(
                url(project, version["id"]), json={"external_tender_id": HUB_ID_V2}
            )

        for response in (created, patched):
            assert response.status_code == 409, response.text
            assert error_code(response) == ErrorCode.TENDER_VERSION_NUMBER_MISMATCH.value
        # Отказанный запрос не оставил черновика.
        assert created.status_code == 409
        assert version["number"] == 1

    async def test_manual_project_cannot_be_linked(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)

        async with portal() as api:
            response = await api.post(url(project), json={"external_tender_id": HUB_ID})

        assert response.status_code == 409
        assert error_code(response) == ErrorCode.TENDER_VERSION_LINK_FORBIDDEN.value

    async def test_hubtender_refusals_keep_their_codes(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)

        async with portal(hub_handler({})) as missing:
            not_found = await missing.post(url(project), json={"external_tender_id": HUB_ID_V2})
        async with portal(integration_off=True) as off:
            disabled = await off.post(url(project), json={"external_tender_id": HUB_ID_V2})

        assert not_found.status_code == 404
        assert error_code(not_found) == ErrorCode.TENDERHUB_TENDER_NOT_FOUND.value
        assert disabled.status_code == 503
        assert error_code(disabled) == ErrorCode.TENDERHUB_DISABLED.value

    async def test_candidates_are_filtered_by_exact_number(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)
        rows = {
            HUB_ID: hub_tender(HUB_ID, version=1),
            HUB_ID_V2: hub_tender(HUB_ID_V2, version=2),
            # Нестрогий поиск HUBTender вернёт и эту строку: номер лишь содержит искомый.
            "33333333-3333-4333-8333-333333333333": hub_tender(
                "33333333-3333-4333-8333-333333333333", number="ТН-0042-А", version=7
            ),
        }

        async with portal(hub_handler(rows)) as api:
            response = await api.get(url(project, "hub-candidates"))

        assert response.status_code == 200
        assert response.json() == [
            {"id": HUB_ID_V2, "version": 2, "submission_deadline": "2026-12-01"},
            {"id": HUB_ID, "version": 1, "submission_deadline": "2026-12-01"},
        ]

    async def test_candidates_are_empty_without_link_or_integration(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        manual = await make_project(db_session, workspace_id)
        linked = await make_project(db_session, workspace_id, hub=True)

        async with portal() as api:
            for_manual = await api.get(url(manual, "hub-candidates"))
        async with portal(integration_off=True) as off:
            for_linked = await off.get(url(linked, "hub-candidates"))

        assert for_manual.status_code == for_linked.status_code == 200
        assert for_manual.json() == for_linked.json() == []

    async def test_versions_work_without_the_integration(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id, hub=True)
        await make_document(db_session, project, "АР")

        async with portal(integration_off=True) as api:
            created = await api.post(url(project), json={})
            frozen = await api.post(url(project, created.json()["id"], "freeze"))

        assert created.status_code == 201
        assert frozen.status_code == 200


# ------------------------------------------------------------ один номер — один проект


class TestOneNumberOneProject:
    @staticmethod
    def hub_portal(
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        rows: dict[str, dict[str, Any]],
        context: AuthContext | None = None,
    ) -> tuple[Any, AsyncClient]:
        app, client = _build_api(db_session, fake_storage, context=context or make_context())

        async def override() -> AsyncIterator[TenderHubClient]:
            async with hub_client(hub_handler(rows)) as hub:
                yield hub

        app.dependency_overrides[get_tenderhub_client] = override
        return app, client

    async def test_other_version_of_the_number_points_to_the_project(
        self, db_session: AsyncSession, fake_storage: FakeObjectStorage
    ) -> None:
        rows = {
            HUB_ID: hub_tender(HUB_ID, version=1),
            HUB_ID_V2: hub_tender(HUB_ID_V2, version=2),
            "44444444-4444-4444-8444-444444444444": hub_tender(
                "44444444-4444-4444-8444-444444444444", number="ТН-0100"
            ),
        }
        app, client = self.hub_portal(db_session, fake_storage, rows)
        try:
            async with client as api:
                created = await api.post(
                    "/api/v1/integrations/tenderhub/projects", json={"tender_id": HUB_ID}
                )
                listing = (await api.get("/api/v1/integrations/tenderhub/tenders")).json()
        finally:
            app.dependency_overrides.clear()

        project_id = created.json()["id"]
        by_id = {row["id"]: row for row in listing}
        assert by_id[HUB_ID]["imported_project_id"] == project_id
        assert by_id[HUB_ID]["same_number_project_id"] is None
        assert by_id[HUB_ID_V2]["imported_project_id"] is None
        assert by_id[HUB_ID_V2]["same_number_project_id"] == project_id
        # Свободный номер подсказки не получает.
        free = by_id["44444444-4444-4444-8444-444444444444"]
        assert free["imported_project_id"] is None
        assert free["same_number_project_id"] is None

    async def test_server_refuses_the_second_project_with_the_same_number(
        self, db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
    ) -> None:
        rows = {HUB_ID: hub_tender(HUB_ID, version=1), HUB_ID_V2: hub_tender(HUB_ID_V2, version=2)}
        app, client = self.hub_portal(db_session, fake_storage, rows)
        try:
            async with client as api:
                first = await api.post(
                    "/api/v1/integrations/tenderhub/projects", json={"tender_id": HUB_ID}
                )
                second = await api.post(
                    "/api/v1/integrations/tenderhub/projects", json={"tender_id": HUB_ID_V2}
                )
        finally:
            app.dependency_overrides.clear()

        assert first.status_code == 201
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["code"] == ErrorCode.TENDERHUB_NUMBER_TAKEN.value
        assert detail["issue"] == {"project_id": first.json()["id"]}
        count = await db_session.execute(
            select(Project.id).where(Project.workspace_id == workspace_id)
        )
        assert len(count.all()) == 1

    async def test_number_of_another_workspace_does_not_block(
        self,
        db_session: AsyncSession,
        fake_storage: FakeObjectStorage,
        second_workspace: Workspace,
    ) -> None:
        await make_project(db_session, second_workspace.id, hub=True, external_id=HUB_ID_V2)
        rows = {HUB_ID: hub_tender(HUB_ID, version=1)}
        app, client = self.hub_portal(db_session, fake_storage, rows)
        try:
            async with client as api:
                listing = (await api.get("/api/v1/integrations/tenderhub/tenders")).json()
                response = await api.post(
                    "/api/v1/integrations/tenderhub/projects", json={"tender_id": HUB_ID}
                )
        finally:
            app.dependency_overrides.clear()

        assert listing[0]["same_number_project_id"] is None
        assert response.status_code == 201


# ----------------------------------------------------------------- триггеры базы


async def rejected(session: AsyncSession, sql: str, params: dict[str, Any], fragment: str) -> None:
    """Прямой SQL обязан упасть на триггере; транзакция после отказа откатывается."""
    with pytest.raises(DBAPIError) as error:
        await session.execute(text(sql), params)
        await session.flush()
    await session.rollback()
    assert fragment in str(error.value)


class TestDatabaseGuards:
    async def frozen_version(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")
        await make_document(db_session, project, "КР")
        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
            frozen: dict[str, Any] = (await api.post(url(project, version["id"], "freeze"))).json()
        return frozen

    async def test_frozen_version_cannot_be_changed_or_deleted(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        version = await self.frozen_version(portal, db_session, workspace_id)
        params = {"id": uuid.UUID(version["id"])}

        await rejected(
            db_session,
            "update tender_versions set label = 'x' where id = :id",
            params,
            "frozen version is immutable",
        )
        await rejected(
            db_session,
            "update tender_versions set status = 'draft', manifest_sha256 = null,"
            " frozen_at = null where id = :id",
            params,
            "frozen version is immutable",
        )
        await rejected(
            db_session,
            "delete from tender_versions where id = :id",
            params,
            "frozen version is immutable",
        )

        row = await db_session.execute(
            text("select status, label from tender_versions where id = :id"), params
        )
        assert tuple(row.one()) == ("frozen", None)

    async def test_composition_of_frozen_version_is_immutable(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        version = await self.frozen_version(portal, db_session, workspace_id)
        params = {"id": uuid.UUID(version["id"])}
        member = version["documents"][0]
        project = await db_session.get(Project, uuid.UUID(version["project_id"]))
        assert project is not None
        extra_document, extra_revisions = await make_document(db_session, project, "ОВ")
        # Откат после каждого отказа сбрасывает объекты сессии: нужные значения берём заранее.
        extra = {"document": extra_document.id, "revision": extra_revisions[0].id}
        fragment = "composition of a frozen version is immutable"

        await rejected(
            db_session,
            "update tender_version_documents set use_in_model = false"
            " where tender_version_id = :id",
            params,
            fragment,
        )
        await rejected(
            db_session,
            "delete from tender_version_documents where tender_version_id = :id",
            params,
            fragment,
        )
        await rejected(
            db_session,
            "insert into tender_version_documents"
            " (id, tender_version_id, document_id, document_revision_id, use_in_model)"
            " values (gen_random_uuid(), :id, :document, :revision, true)",
            {**params, **extra},
            fragment,
        )
        # Строку нельзя и «перевесить» на другую версию.
        await rejected(
            db_session,
            "update tender_version_documents set tender_version_id = gen_random_uuid()"
            " where document_id = :document",
            {"document": uuid.UUID(member["document_id"])},
            fragment,
        )

        count = await db_session.execute(
            text("select count(*) from tender_version_documents where tender_version_id = :id"),
            params,
        )
        assert count.scalar_one() == 2

    async def test_draft_is_not_blocked_by_the_triggers(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        await make_document(db_session, project, "АР")
        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
        params = {"id": uuid.UUID(version["id"])}

        await db_session.execute(
            text(
                "update tender_version_documents set section = 'АР' where tender_version_id = :id"
            ),
            params,
        )
        await db_session.execute(
            text("update tender_versions set label = 'x' where id = :id"), params
        )
        await db_session.execute(text("delete from tender_versions where id = :id"), params)
        await db_session.commit()

        left = await db_session.execute(text("select count(*) from tender_version_documents"))
        assert left.scalar_one() == 0

    async def test_frozen_status_requires_manifest_and_time(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        async with portal() as api:
            version = (await api.post(url(project), json={})).json()
        params = {"id": uuid.UUID(version["id"])}

        with pytest.raises(IntegrityError) as error:
            await db_session.execute(
                text("update tender_versions set status = 'frozen' where id = :id"), params
            )
            await db_session.flush()
        await db_session.rollback()

        assert "frozen_has_manifest" in str(error.value)

    async def test_only_one_draft_per_project_in_the_database(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        project = await make_project(db_session, workspace_id)
        async with portal() as api:
            await api.post(url(project), json={})

        with pytest.raises(IntegrityError) as error:
            await db_session.execute(
                text(
                    "insert into tender_versions (id, workspace_id, project_id, number, status)"
                    " values (gen_random_uuid(), :workspace, :project, 2, 'draft')"
                ),
                {"workspace": workspace_id, "project": project.id},
            )
            await db_session.flush()
        await db_session.rollback()

        assert "uq_tender_versions_draft" in str(error.value)

    async def test_revision_of_a_version_cannot_be_deleted(
        self,
        portal: Callable[..., AsyncClient],
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> None:
        version = await self.frozen_version(portal, db_session, workspace_id)
        revision_id = uuid.UUID(version["documents"][0]["document_revision_id"])

        with pytest.raises(IntegrityError) as error:
            await db_session.execute(
                text("delete from document_revisions where id = :id"), {"id": revision_id}
            )
            await db_session.flush()
        await db_session.rollback()

        assert "fk_tender_version_documents_document_revision_id" in str(error.value)
