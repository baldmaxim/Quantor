'use client';

import type { FC } from 'react';

import { ConstructionsTotals } from '@/components/workspace/cad/ConstructionsTotals';
import { WALLS_NOT_READY, useCadConstructions } from '@/lib/cad/constructions-queries';
import { cadErrorText } from '@/lib/cad/errors';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { extractCode } from '@/lib/errors';
import { Skeleton } from '@/components/ui';

interface IBuildingFloorTotalsProps {
  /** Параметры чтения листа; `null` - читать нечего. */
  readonly params: ICadViewParams | null;
  /** Задание листа ещё читается. */
  readonly pending: boolean;
}

const NO_OP = (): void => undefined;

/** Итоги конструкций листа этажа: считает сервер, здесь только показ (свод без выбора групп). */
export const BuildingFloorTotals: FC<IBuildingFloorTotalsProps> = ({ params, pending }) => {
  const query = useCadConstructions(params, true);

  if (pending || (params !== null && query.isPending)) {
    return (
      <div role="status" aria-label="Загрузка итогов" className="flex flex-col gap-[var(--s-2)]">
        <Skeleton className="h-[12px] w-full" />
        <Skeleton className="h-[12px] w-[70%]" />
        <Skeleton className="h-[12px] w-[85%]" />
      </div>
    );
  }
  if (params === null) {
    return <p className="text-xs text-muted">Итоги недоступны: у листа нет готового результата CAD.</p>;
  }
  if (query.isError || query.data === undefined) {
    return (
      <p role="status" className="text-xs text-muted [overflow-wrap:anywhere]">
        {extractCode(query.error) === WALLS_NOT_READY
          ? 'Конструкции листа ещё не посчитаны.'
          : cadErrorText(query.error)}
      </p>
    );
  }
  return (
    <div className="max-w-full overflow-x-auto [overscroll-behavior:contain]">
      <ConstructionsTotals data={query.data} activeGroup={null} onSelectGroup={NO_OP} />
    </div>
  );
};
