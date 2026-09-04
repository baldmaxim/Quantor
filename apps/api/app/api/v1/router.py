"""Сборка маршрутов /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import meta

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(meta.router)
