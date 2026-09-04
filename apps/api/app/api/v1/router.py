"""Сборка маршрутов /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import documents, jobs, meta, projects, uploads

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(meta.router)
api_v1_router.include_router(projects.router)
api_v1_router.include_router(uploads.router)
api_v1_router.include_router(documents.router)
api_v1_router.include_router(jobs.router)
