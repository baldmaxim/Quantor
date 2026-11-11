'use client';

import dynamic from 'next/dynamic';

import type { ICadBuilding3dColumnProps } from './CadBuilding3dColumn';

/**
 * Колонка «Здание» грузится отдельным чанком только вместе с видом «3D»: `three` не попадает в
 * чанк маршрута рабочей области.
 */
export const CadBuilding3dLazy = dynamic<ICadBuilding3dColumnProps>(
  () => import('./CadBuilding3dColumn').then((module) => module.CadBuilding3dColumn),
  {
    ssr: false,
    loading: () => (
      <div role="status" className="p-[var(--s-5)] text-sm text-muted">
        Загружаем здание…
      </div>
    ),
  },
);
