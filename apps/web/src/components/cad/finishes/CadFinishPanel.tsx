'use client';

import type { FC } from 'react';

import { useCadFinishTemplates } from '@/lib/cad/finishes-queries';

import { CadFinishSheet } from './CadFinishSheet';
import { CadFinishTemplates } from './CadFinishTemplates';

export interface ICadFinishPanelProps {
  projectId: string;
  revisionId: string | null;
  /** Индекс страницы открытого листа; `null` - лист не выбран. */
  pageIndex: number | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась: без него запросов нет. */
  load: boolean;
  /** Выбранная на листе зона: подсвечивается в ведомости. */
  activeId: string | null;
  /** Выделить зону на листе (то же, что выбор в списке зон). */
  onActivate: (id: string | null) => void;
}

/** Раздел «Отделка» правой панели CAD: шаблоны проекта и ведомость текущего листа (ADR-0042). */
export const CadFinishPanel: FC<ICadFinishPanelProps> = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  activeId,
  onActivate,
}) => {
  // Тот же запрос, что в списке шаблонов: кеш общий, лишнего обращения нет.
  const templates = useCadFinishTemplates(projectId, load);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-6)]" data-testid="cad-finish-panel">
      <CadFinishTemplates projectId={projectId} load={load} />
      <CadFinishSheet
        projectId={projectId}
        revisionId={revisionId}
        pageIndex={pageIndex}
        load={load}
        templates={templates.data ?? []}
        activeId={activeId}
        onActivate={onActivate}
      />
    </div>
  );
};
