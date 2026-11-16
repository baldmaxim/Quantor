'use client';

import type { FC, ReactNode } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadJobList } from '@/components/cad/CadJobList';
import { CadResult } from '@/components/cad/CadResult';
import { CadFilesSection } from '@/components/cad/viewer/CadFilesSection';
import { CadScaleSection } from '@/components/cad/viewer/CadScaleSection';
import { CadViewHeader } from '@/components/cad/viewer/CadViewHeader';
import { ErrorState, Skeleton } from '@/components/ui';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';

import { CadStylePanel } from './CadStylePanel';
import type { IWorkspaceCadLeftProps, IWorkspaceCadSideProps } from './types';

/** Список заданий ревизии: выбор задания переводит рабочую область на его лист. */
export type WorkspaceCadSheetJobs = Pick<
  IWorkspaceCadLeftProps,
  'projectId' | 'revisionId' | 'selectedJobId' | 'onSelectJob'
>;

interface IWorkspaceCadSheetTabProps
  extends Pick<
    IWorkspaceCadSideProps,
    'sheetLabel' | 'floorTitle' | 'job' | 'viewLoading' | 'viewError' | 'view' | 'style'
  > {
  readonly jobs?: WorkspaceCadSheetJobs | null;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

interface IFoldProps {
  readonly title: string;
  readonly children: ReactNode;
}

/** Сворачиваемый блок: содержимое остаётся смонтированным и в свёрнутом виде. */
const Fold: FC<IFoldProps> = ({ title, children }) => (
  <details className="flex min-w-0 flex-col gap-[var(--s-2)]">
    <summary className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}>
      {title}
    </summary>
    <div className="min-w-0 pt-[var(--s-3)]">{children}</div>
  </details>
);

/**
 * Раздел «Лист» правой панели CAD: всё про сам лист и его преобразование - сводка вида, масштаб,
 * файлы, ход преобразования, профиль оформления тома и задания документа. У листа без задания -
 * подсказка о запуске; у идущего или упавшего задания - его ход открыт.
 */
export const WorkspaceCadSheetTab: FC<IWorkspaceCadSheetTabProps> = ({
  sheetLabel,
  floorTitle = null,
  job,
  viewLoading,
  viewError,
  view,
  style = null,
  jobs = null,
}) => {
  const shared = (
    <>
      {style && (
        <Fold title="Профиль оформления">
          <CadStylePanel {...style} />
        </Fold>
      )}
      {jobs && (
        <Fold title="Задания документа">
          <CadJobList
            // Ключ по ревизии: список другого документа не переиспользуется.
            key={jobs.revisionId}
            projectId={jobs.projectId}
            revisionId={jobs.revisionId}
            selectedJobId={jobs.selectedJobId}
            onSelect={jobs.onSelectJob}
          />
        </Fold>
      )}
    </>
  );

  if (job === null) {
    return (
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
        <div className="flex flex-col gap-[var(--s-3)]" data-testid="workspace-cad-none">
          {sheetLabel !== null && (
            <p className="text-xs text-muted">
              {floorTitle !== null && formatFloorTitle(floorTitle, '') !== '' && (
                <>
                  <span className="text-text" title={formatFloorTitleFull(floorTitle) ?? undefined}>
                    {formatFloorTitle(floorTitle, '')}
                  </span>
                  {' · '}
                </>
              )}
              Лист <span className="text-text">{sheetLabel}</span>
            </p>
          )}
          <p className="text-sm">Лист не преобразовывался</p>
          <p className="text-xs text-muted">
            Запустите преобразование: нажмите статус листа вверху справа, результат появится здесь.
          </p>
        </div>
        {shared}
      </div>
    );
  }

  const detail = (
    <CadJobDetail
      // Ключ по заданию: попытка, выбранная вручную, не переходит на другое задание.
      key={`${job.revisionId}:${job.jobId}`}
      projectId={job.projectId}
      revisionId={job.revisionId}
      jobId={job.jobId}
      selectedPage={job.page}
      selectedView={job.view}
      onSelectView={job.onSelectView}
    />
  );

  if (!view) {
    return (
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
        {detail}
        {shared}
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
      <CadViewHeader diagnostics={view.diagnostics} />
      <CadScaleSection scale={view.diagnostics.scale} />
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]" data-testid="workspace-cad-files">
        {job.detail && (
          <CadResult
            projectId={job.projectId}
            revisionId={job.revisionId}
            job={job.detail}
            // Файлы принадлежат попытке с результатом; без неё - текущей.
            attempt={job.detail.result_attempt ?? job.detail.attempt}
          />
        )}
        <CadFilesSection
          projectId={job.projectId}
          revisionId={job.revisionId}
          jobId={job.jobId}
          diagnostics={view.diagnostics}
        />
      </div>
      <Fold title="Ход преобразования">{detail}</Fold>
      {shared}
    </div>
  );
};
