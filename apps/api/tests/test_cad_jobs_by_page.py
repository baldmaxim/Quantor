"""Список заданий CAD ревизии: фильтр `page_index` отдаёт задания листа сквозь окно в 20 заданий."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from tests.conftest import FakeObjectStorage, make_context
from tests.doc_questions_support import add_pdf, make_project
from tests.test_cad_queue import add_job, queue_settings


async def test_page_filter_finds_old_jobs_of_the_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        base = {"revision_id": str(revision.id)}
        common = {"workspace_id": workspace_id, "project_id": pid, "status": JobStatus.SUCCEEDED}

        # Старые задания страницы 5: преобразование (вместе с другой страницей) и трассы.
        convert = add_job(
            db_session, **common, minutes=-100, payload={**base, "params": {"pages": [3, 5]}}
        )
        routes = add_job(
            db_session,
            **common,
            minutes=-90,
            job_type=JobType.CAD_MEP_ROUTE,
            payload={**base, "page_index": 5, "view": 0},
        )
        # Трассы другой страницы и 25 новых преобразований других страниц.
        other_routes = add_job(
            db_session,
            **common,
            minutes=-80,
            job_type=JobType.CAD_MEP_ROUTE,
            payload={**base, "page_index": 6, "view": 0},
        )
        others = [
            add_job(
                db_session,
                **common,
                minutes=index,
                payload={**base, "params": {"pages": [10 + index]}},
            )
            for index in range(25)
        ]
        await db_session.commit()

        url = f"/api/v1/projects/{project_id}/revisions/{revision.id}/cad"
        all_ids = {item["job_id"] for item in (await api.get(url)).json()["items"]}
        assert len(all_ids) == 20
        assert str(convert.id) not in all_ids and str(routes.id) not in all_ids
        assert all_ids <= {str(job.id) for job in others}

        response = await api.get(url, params={"page_index": 5})
        assert response.status_code == 200, response.text
        ids = [item["job_id"] for item in response.json()["items"]]
        assert ids == [str(routes.id), str(convert.id)]
        assert str(other_routes.id) not in ids

        empty = await api.get(url, params={"page_index": 99})
        assert empty.json()["items"] == []
        assert (await api.get(url, params={"page_index": -1})).status_code == 422
