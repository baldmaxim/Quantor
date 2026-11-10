'use client';

import { useState, type FC } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadChecksSection } from '@/components/cad/viewer/CadChecksSection';
import { CadFilesSection } from '@/components/cad/viewer/CadFilesSection';
import { CadLayersPanel } from '@/components/cad/viewer/CadLayersPanel';
import { CadRemarksPanel } from '@/components/cad/viewer/CadRemarksPanel';
import { CadScaleSection } from '@/components/cad/viewer/CadScaleSection';
import { CadSidePanel, type ICadSideTab } from '@/components/cad/viewer/CadSidePanel';
import { CadViewHeader } from '@/components/cad/viewer/CadViewHeader';
import { Button, ErrorState, Skeleton, SkeletonRows } from '@/components/ui';

import type { IWorkspaceCadSideProps } from './types';

const HINT = 'p-[var(--s-5)] text-xs text-muted';

/**
 * Правая панель вкладки CAD: слои, замечания, масштаб, файлы и задание листа рабочей области.
 *
 * Лист без задания, с идущим или упавшим заданием получает только раздел «Задание» (или
 * подсказку): диагностики вида у него нет. Ширину и сворачивание панели ведёт каркас рабочей
 * области.
 */
export const WorkspaceCadSide: FC<IWorkspaceCadSideProps> = ({
  state,
  sheetLabel,
  loadError,
  onRetry,
  job,
  viewLoading,
  viewError,
  view,
}) => {
  // Раздел живёт здесь: при переходе на другой лист панель остаётся на выбранном разделе.
  const [sideTab, setSideTab] = useState('layers');

  if (state === 'no-sheet') return <p className={HINT}>Лист не выбран.</p>;

  if (state === 'loading') {
    return (
      <div className="p-[var(--s-5)]" role="status" aria-label="Загрузка заданий CAD">
        <SkeletonRows rows={3} />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div role="alert" className="flex flex-col gap-[var(--s-3)] p-[var(--s-5)] text-xs text-danger">
        <span>Не удалось загрузить задания CAD. {loadError}</span>
        <Button compact onClick={onRetry} className="self-start max-md:h-[44px]">
          Повторить
        </Button>
      </div>
    );
  }

  if (state === 'none' || job === null) {
    return (
      <div className="flex flex-col gap-[var(--s-3)] p-[var(--s-5)]" data-testid="workspace-cad-none">
        {sheetLabel !== null && (
          <p className="text-xs text-muted">
            Лист <span className="text-text">{sheetLabel}</span>
          </p>
        )}
        <p className="text-sm">Лист не преобразовывался</p>
        <p className="text-xs text-muted">
          Отметьте лист слева и запустите преобразование: результат появится здесь.
        </p>
      </div>
    );
  }

  const jobTab: ICadSideTab = {
    id: 'job',
    label: 'Задание',
    content: (
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
        {viewLoading && (
          <div className="flex flex-col gap-[var(--s-3)]" role="status" aria-label="Загрузка вида">
            <Skeleton className="h-[20px] w-[60%]" />
            <Skeleton className="h-[16px] w-[80%]" />
          </div>
        )}
        {viewError && (
          <ErrorState
            title="Результат CAD не загружен"
            code={viewError.code}
            description={viewError.text}
          />
        )}
        {view && <CadViewHeader diagnostics={view.diagnostics} />}
        <CadJobDetail
          // Ключ по заданию: попытка, выбранная вручную, не переходит на другое задание.
          key={`${job.revisionId}:${job.jobId}`}
          projectId={job.projectId}
          revisionId={job.revisionId}
          jobId={job.jobId}
          selectedPage={job.page}
          selectedView={job.view}
          onSelectView={job.onSelectView}
          onJobCreated={job.onJobCreated}
        />
      </div>
    ),
  };

  const tabs: readonly ICadSideTab[] = view
    ? [
        {
          id: 'layers',
          label: 'Слои',
          content: <CadLayersPanel {...view.layers} />,
        },
        {
          id: 'remarks',
          label: 'Замечания',
          content: view.remarks ? <CadRemarksPanel {...view.remarks} /> : null,
        },
        {
          id: 'scale',
          label: 'Масштаб',
          content: (
            <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
              <CadScaleSection scale={view.diagnostics.scale} />
              <CadChecksSection checks={view.diagnostics.checks} frame={view.diagnostics.frame} />
            </div>
          ),
        },
        {
          id: 'files',
          label: 'Файлы',
          content: (
            <CadFilesSection
              projectId={job.projectId}
              revisionId={job.revisionId}
              jobId={job.jobId}
              diagnostics={view.diagnostics}
            />
          ),
        },
        jobTab,
      ]
    : [jobTab];

  return (
    <CadSidePanel label="Панель CAD" tabs={tabs} active={sideTab} onActiveChange={setSideTab} />
  );
};
