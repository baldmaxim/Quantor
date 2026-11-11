'use client';

import type { FC } from 'react';

import type { IFloor3dCenter } from '@/lib/cad/floor3d-geometry';
import { measureLabel, type IScreenPoint, type SceneVec3 } from '@/lib/cad/floor3d-measure';

interface ICadFloor3dMeasureLabelProps {
  readonly a: SceneVec3;
  readonly b: SceneVec3;
  readonly center: IFloor3dCenter;
  /** Середина отрезка на экране, px от угла холста. */
  readonly at: IScreenPoint;
}

/** Подпись замера: расстояние и приращения в мм DXF, над холстом у середины отрезка. */
export const CadFloor3dMeasureLabel: FC<ICadFloor3dMeasureLabelProps> = ({ a, b, center, at }) => {
  const text = measureLabel(a, b, center);
  return (
    <div
      data-testid="floor3d-measure-label"
      // Положение следует за камерой - динамическое значение.
      style={{ left: at.x, top: at.y }}
      className="pointer-events-none absolute z-10 flex -translate-x-1/2 -translate-y-full flex-col items-center gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border-strong bg-surface-raised px-[var(--s-3)] py-[var(--s-2)] text-xs whitespace-nowrap shadow-[var(--shadow-2)]"
    >
      <span className="font-semibold">{text.distance}</span>
      <span className="text-muted">{text.deltas}</span>
    </div>
  );
};
