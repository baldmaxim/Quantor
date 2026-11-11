'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { CadBuilding3dLazy } from '@/components/workspace/cad/building3d/CadBuilding3dLazy';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadFloor3dLazy } from './CadFloor3dLazy';

export interface ICadFloor3dOverlayProps {
  projectId: string;
  /** Параметры показанного листа; `null` - новый этаж ещё грузится. */
  params: ICadViewParams | null;
  onSelectFloor: (floor: CadBuilding3dFloorRead) => void;
  /** Выход в «План», пока этаж грузится (панели вида ещё нет). */
  onExit: () => void;
}

const keyOf = (params: ICadViewParams) => `${params.jobId}:${params.pageIndex}:${params.view}`;

/**
 * Оверлей «3D» поверх холста. Пока новый этаж грузится, оверлей не снимается: колонка «Здание»
 * остаётся на месте, вместо этажа - заглушка; 2D-план под ним не мелькает.
 */
export const CadFloor3dOverlay: FC<ICadFloor3dOverlayProps> = ({ projectId, params, onSelectFloor, onExit }) => {
  const [last, setLast] = useState<ICadViewParams | null>(params);
  if (params !== null && (last === null || keyOf(last) !== keyOf(params))) setLast(params);
  const current = params ?? last;

  return (
    <div className="absolute inset-0 z-20 flex min-h-0 flex-col bg-bg lg:flex-row">
      {current && (
        <CadBuilding3dLazy
          projectId={projectId}
          current={{ jobId: current.jobId, pageIndex: current.pageIndex, view: current.view }}
          onSelectFloor={onSelectFloor}
        />
      )}
      <div className="relative min-h-0 min-w-0 flex-1">
        {params ? (
          <CadFloor3dLazy key={keyOf(params)} params={params} />
        ) : (
          <div role="status" className="absolute inset-0 grid place-items-center bg-bg text-sm text-muted">
            <div className="grid justify-items-center gap-[var(--s-3)]">
              <span>Загружаем этаж…</span>
              <Button onClick={onExit}>План</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
