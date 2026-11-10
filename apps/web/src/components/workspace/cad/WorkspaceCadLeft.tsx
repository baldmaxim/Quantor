'use client';

import { useState, type FC } from 'react';

import { CadJobList } from '@/components/cad/CadJobList';
import { CadSheetPicker } from '@/components/cad/CadSheetPicker';
import { CadSourcePicker } from '@/components/cad/CadSourcePicker';
import { CadTabs, type ICadTab } from '@/components/cad/CadTabs';

import type { IWorkspaceCadLeftProps } from './types';

type LeftTab = 'sheets' | 'jobs';

const LEFT_TABS: readonly ICadTab<LeftTab>[] = [
  { id: 'sheets', label: 'Листы' },
  { id: 'jobs', label: 'Задания' },
];

/**
 * Левая панель вкладки CAD: листы ревизии (выбор, калибровка, запуск, результат) и задания.
 *
 * Клик по листу переводит рабочую область на него. Источник PDF - загрузка нового файла или
 * другой PDF проекта - свёрнут в строку: ревизия в основном уже открыта в рабочей области.
 */
export const WorkspaceCadLeft: FC<IWorkspaceCadLeftProps> = ({
  projectId,
  revisionId,
  activePage,
  selectedJobId,
  onOpenSheet,
  onSelectJob,
  onJobCreated,
  onSourceSelect,
}) => {
  const [tab, setTab] = useState<LeftTab>('sheets');

  return (
    <div
      className="flex min-w-0 flex-col gap-[var(--s-4)] p-[var(--s-4)]"
      data-testid="workspace-cad-left"
    >
      <details className="rounded-[var(--radius-md)] border border-border">
        <summary className="flex min-h-[44px] cursor-pointer items-center px-[var(--s-5)] text-sm">
          Исходный PDF: загрузить или выбрать
        </summary>
        <div className="p-[var(--s-3)]">
          <CadSourcePicker
            projectId={projectId}
            selectedRevisionId={revisionId}
            onSelect={onSourceSelect}
          />
        </div>
      </details>

      <CadTabs
        bare
        idPrefix="ws-cad-left"
        label="Листы и задания ревизии"
        tabs={LEFT_TABS}
        active={tab}
        onChange={setTab}
      >
        {/* Листы не размонтируются при переключении: иначе сбросится выбор отмеченных. */}
        <div hidden={tab !== 'sheets'}>
          <CadSheetPicker
            // Ключ по ревизии: выбор листов другого документа не переиспользуется.
            key={`sheets:${revisionId}`}
            projectId={projectId}
            revisionId={revisionId}
            onJobCreated={onJobCreated}
            activePage={activePage}
            onOpenSheet={onOpenSheet}
          />
        </div>
        {tab === 'jobs' && (
          <CadJobList
            // Ключ по ревизии: список другого документа не переиспользуется.
            key={revisionId}
            projectId={projectId}
            revisionId={revisionId}
            selectedJobId={selectedJobId}
            onSelect={onSelectJob}
          />
        )}
      </CadTabs>
    </div>
  );
};
