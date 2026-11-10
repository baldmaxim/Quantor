'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState, type FC } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadJobList } from '@/components/cad/CadJobList';
import { CadSheetPicker } from '@/components/cad/CadSheetPicker';
import { CadSourcePicker } from '@/components/cad/CadSourcePicker';
import { CadTabs, type ICadTab } from '@/components/cad/CadTabs';
import {
  parseSelection,
  selectionQuery,
  withJob,
  withJobView,
  withRevision,
  withView,
  type ICadSelection,
} from '@/lib/cad/selection';

type LeftTab = 'sheets' | 'jobs';

const LEFT_TABS: readonly ICadTab<LeftTab>[] = [
  { id: 'sheets', label: 'Листы' },
  { id: 'jobs', label: 'Задания' },
];

interface ICadScreenProps {
  projectId: string;
}

/** Экран PDF → CAD: выбор источника слева, ход и результат выбранного задания справа. */
export const CadScreen: FC<ICadScreenProps> = ({ projectId }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selection = parseSelection(searchParams);
  // Вкладка живёт только в состоянии: в адрес не пишем, чтобы ссылка не меняла раскладку.
  const [leftTab, setLeftTab] = useState<LeftTab>('sheets');

  // replace, а не push: переключение вида не должно засорять историю браузера.
  const navigate = (next: ICadSelection) => {
    const query = selectionQuery(next);
    router.replace(`/projects/${projectId}/cad${query ? `?${query}` : ''}`, { scroll: false });
  };

  return (
    <div className="mx-auto grid w-full max-w-[1400px] items-start gap-[var(--s-6)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)]">
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
        <CadSourcePicker
          projectId={projectId}
          selectedRevisionId={selection.revision}
          onSelect={(revisionId) => navigate(withRevision(revisionId))}
        />
        {selection.revision && (
          <CadTabs
            idPrefix="cad-left"
            label="Листы и задания ревизии"
            tabs={LEFT_TABS}
            active={leftTab}
            onChange={setLeftTab}
          >
            {/* Листы не размонтируются при переключении: иначе сбросится выбор отмеченных. */}
            <div hidden={leftTab !== 'sheets'}>
              <CadSheetPicker
                // Ключ по ревизии: выбор листов другого документа не переиспользуется.
                key={`sheets:${selection.revision}`}
                projectId={projectId}
                revisionId={selection.revision}
                onJobCreated={(jobId) => navigate(withJob(selection, jobId))}
                openJobId={selection.job}
                openPage={selection.page}
                onOpenResult={(jobId, page, view) =>
                  navigate(withJobView(selection, jobId, page, view))
                }
              />
            </div>
            {leftTab === 'jobs' && (
              <CadJobList
                // Ключ по ревизии: список другого документа не переиспользуется.
                key={selection.revision}
                projectId={projectId}
                revisionId={selection.revision}
                selectedJobId={selection.job}
                onSelect={(jobId) => navigate(withJob(selection, jobId))}
              />
            )}
          </CadTabs>
        )}
      </div>

      <div className="min-w-0">
        {selection.revision && selection.job ? (
          <CadJobDetail
            key={`${selection.revision}:${selection.job}`}
            projectId={projectId}
            revisionId={selection.revision}
            jobId={selection.job}
            selectedPage={selection.page}
            selectedView={selection.view}
            onSelectView={(page, view) => navigate(withView(selection, page, view))}
            onJobCreated={(jobId) => navigate(withJob(selection, jobId))}
          />
        ) : (
          <p className="rounded-[var(--radius-md)] border border-dashed border-border-strong px-[var(--s-6)] py-[var(--s-7)] text-center text-sm text-muted">
            Загрузите PDF или выберите документ проекта, затем отметьте откалиброванные листы и
            запустите преобразование.
          </p>
        )}
      </div>
    </div>
  );
};
