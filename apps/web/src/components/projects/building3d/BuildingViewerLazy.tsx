'use client';

import dynamic from 'next/dynamic';

import type { IBuildingViewerProps } from './BuildingViewer';

/**
 * Просмотрщик объекта грузится отдельным чанком: `three` не попадает в чанк страницы, пока она не
 * открыта (и не тянется на главную проекта).
 */
export const BuildingViewerLazy = dynamic<IBuildingViewerProps>(
  () => import('./BuildingViewer').then((module) => module.BuildingViewer),
  {
    ssr: false,
    loading: () => (
      <div role="status" className="p-[var(--s-5)] text-sm text-muted">
        Загружаем здание…
      </div>
    ),
  },
);
