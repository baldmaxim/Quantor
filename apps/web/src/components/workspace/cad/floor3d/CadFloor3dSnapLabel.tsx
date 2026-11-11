'use client';

import type { FC } from 'react';

import type { IFloor3dSnapState } from '@/lib/cad/floor3d-engine';
import { SNAP_KIND_LABELS } from '@/lib/cad/floor3d-measure';

interface ICadFloor3dSnapLabelProps {
  readonly snap: IFloor3dSnapState;
}

/** Короткая подпись у маркера привязки: «угол», «ребро» или «грань». */
export const CadFloor3dSnapLabel: FC<ICadFloor3dSnapLabelProps> = ({ snap }) => (
  <div
    data-testid="floor3d-snap-label"
    // Положение следует за курсором - динамическое значение.
    style={{ left: snap.at.x + 12, top: snap.at.y + 12 }}
    className="pointer-events-none absolute z-10 rounded-[var(--radius-sm)] border border-border-strong bg-surface-raised px-[var(--s-2)] py-[var(--s-1)] text-xs whitespace-nowrap shadow-[var(--shadow-2)]"
  >
    {SNAP_KIND_LABELS[snap.kind]}
  </div>
);
