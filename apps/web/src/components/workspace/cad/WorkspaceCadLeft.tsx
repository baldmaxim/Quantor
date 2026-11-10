'use client';

import { useState, type FC } from 'react';

import { CadJobList } from '@/components/cad/CadJobList';
import { CadSheetPicker } from '@/components/cad/CadSheetPicker';
import { CadTabs, type ICadTab } from '@/components/cad/CadTabs';

import type { IWorkspaceCadLeftProps } from './types';

type LeftTab = 'sheets' | 'jobs';

const LEFT_TABS: readonly ICadTab<LeftTab>[] = [
  { id: 'sheets', label: 'Листы' },
  { id: 'jobs', label: 'Задания' },
];

/**
 * Левая панель вкладки CAD: листы ревизии и задания.
 *
 * Клик по листу переводит рабочую область на него; преобразование листа запускается в правой
 * панели. Исходный PDF выбирают в рабочей области, здесь его нет.
 */
export const WorkspaceCadLeft: FC<IWorkspaceCadLeftProps> = ({
  projectId,
  revisionId,
  activePage,
  selectedJobId,
  onOpenSheet,
  onSelectJob,
}) => {
  const [tab, setTab] = useState<LeftTab>('sheets');

  return (
    <div
      className="flex min-w-0 flex-col gap-[var(--s-4)] p-[var(--s-4)]"
      data-testid="workspace-cad-left"
    >
      <CadTabs
        bare
        idPrefix="ws-cad-left"
        label="Листы и задания ревизии"
        tabs={LEFT_TABS}
        active={tab}
        onChange={setTab}
      >
        {/* Листы не размонтируются при переключении: список не перечитывается заново. */}
        <div hidden={tab !== 'sheets'}>
          <CadSheetPicker
            // Ключ по ревизии: выбор листов другого документа не переиспользуется.
            key={`sheets:${revisionId}`}
            projectId={projectId}
            revisionId={revisionId}
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
