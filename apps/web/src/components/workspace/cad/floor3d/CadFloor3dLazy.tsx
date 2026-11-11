'use client';

import dynamic from 'next/dynamic';

import type { ICadFloor3dViewProps } from './CadFloor3dView';

/**
 * Вид «3D» грузится отдельным чанком только при открытии (ADR-0039 п. 2): `three` не попадает в
 * чанк маршрута рабочей области, пока режим «3D» не включён.
 */
export const CadFloor3dLazy = dynamic<ICadFloor3dViewProps>(
  () => import('./CadFloor3dView').then((module) => module.CadFloor3dView),
  {
    ssr: false,
    loading: () => (
      <div role="status" className="absolute inset-0 z-20 grid place-items-center bg-bg text-sm text-muted">
        Загружаем 3D-вид…
      </div>
    ),
  },
);
