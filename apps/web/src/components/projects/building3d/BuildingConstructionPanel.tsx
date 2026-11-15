'use client';

import type { CadConstructionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { ConstructionComputed } from '@/components/workspace/cad/ConstructionComputed';
import { constructionTitle } from '@/lib/cad/construction-labels';

interface IBuildingConstructionPanelProps {
  /** Выбранная конструкция; `null` - данных нет (ещё читаются или конструкции нет в расчёте листа). */
  readonly construction: CadConstructionRead | null;
  /** Двери в стене этой конструкции. */
  readonly doors: number;
  /** Объяснение, почему карточки нет: чтение, ошибка, не найдена. */
  readonly note: string | null;
  readonly onClear: () => void;
}

/** Параметры выбранной в 3D конструкции: тот же блок «Расчёт», что в карточке конструкции рабочей области, только чтение. */
export const BuildingConstructionPanel: FC<IBuildingConstructionPanelProps> = ({
  construction,
  doors,
  note,
  onClear,
}) => (
  <section aria-label="Конструкция" className="flex min-w-0 flex-col gap-[var(--s-3)] p-[var(--s-4)]">
    <h2 className="text-base font-medium [overflow-wrap:anywhere]">
      {construction === null ? 'Конструкция' : constructionTitle(construction)}
    </h2>
    {construction === null ? (
      note !== null && (
        <p role="status" className="text-sm text-muted [overflow-wrap:anywhere]">
          {note}
        </p>
      )
    ) : (
      <ConstructionComputed construction={construction} doors={doors} />
    )}
    <div>
      <Button className="md:h-8" onClick={onClear}>
        Снять выбор
      </Button>
    </div>
  </section>
);
