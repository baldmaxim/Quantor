'use client';

import type { FC } from 'react';

import { Button, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import { issuesOfPage, isSectionsJobActive, levelsOfPage } from '@/lib/cad/sections';
import { jobLabel, jobTone } from '@/lib/cad/stages';

import { CadSectionsPage } from './CadSectionsPage';
import type { IWorkspaceCadSections } from './types';

/**
 * Вкладка «Разрезы» - только на странице-разрезе: повторный запуск распознавания, кандидаты
 * уровней страницы и решения человека. Со страниц плана разрезы открывают из запуска трасс.
 * Принятые уровни уходят в запуск трасс как высота в свету; кандидаты и отклонённые - нет.
 */
export const CadSectionsPanel: FC<IWorkspaceCadSections> = ({
  status,
  data,
  loadError,
  onReload,
  pageIndex,
  starting,
  onStart,
  deciding,
  onDecide,
  actionError,
  activeLevelId,
  onSelectLevel,
  markupVisible,
  onMarkupVisibleChange,
}) => {
  if (status === 'loading') {
    return (
      <div role="status" aria-label="Загрузка разрезов">
        <SkeletonRows rows={3} />
      </div>
    );
  }
  if (status === 'error' || data === null) {
    return (
      <ErrorState
        title="Разрезы не загружены"
        description={loadError ?? undefined}
        onRetry={onReload}
      />
    );
  }

  const { job } = data;
  const running = starting || isSectionsJobActive(job?.status);
  const page = pageIndex === null ? undefined : data.pages.find((item) => item.page_index === pageIndex);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="cad-sections">
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <Button
          variant="primary"
          loading={running}
          onClick={onStart}
          className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
        >
          {job === null ? 'Распознать разрезы' : 'Распознать разрезы заново'}
        </Button>
        {job !== null && (
          <div className="flex min-w-0 flex-col gap-[var(--s-2)]" role="status" aria-live="polite">
            <span className="flex flex-wrap items-center gap-[var(--s-3)]">
              <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
              <span className="mono text-xs text-muted">попытка {job.attempt}</span>
            </span>
            {isSectionsJobActive(job.status) && (
              <p className="text-xs text-muted">Разрезы распознаются. Список обновится сам.</p>
            )}
            {job.status === 'failed' && (
              <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
                {job.error_code ? cadCodeText(job.error_code) : 'Разрезы не распознаны.'}
                {job.error_message ? ` ${job.error_message}` : ''}
              </p>
            )}
          </div>
        )}
        {actionError !== null && (
          <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
            {actionError}
          </p>
        )}
      </div>

      {data.result_job_id === null ? (
        <p className="text-xs text-muted">
          Разрезы ещё не распознавались: запустите распознавание, результат появится здесь.
        </p>
      ) : (
        <>
          <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
            <input
              type="checkbox"
              checked={markupVisible}
              onChange={(event) => onMarkupVisibleChange(event.target.checked)}
              className="size-5 shrink-0"
            />
            Разметка разрезов на листе
          </label>
          {page !== undefined && pageIndex !== null && (
            <CadSectionsPage
              page={page}
              levels={levelsOfPage(data.levels, pageIndex)}
              issues={issuesOfPage(data.issues, pageIndex)}
              busy={deciding}
              activeLevelId={activeLevelId}
              onSelectLevel={onSelectLevel}
              onDecide={onDecide}
            />
          )}
        </>
      )}
    </div>
  );
};
