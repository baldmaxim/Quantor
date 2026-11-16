'use client';

import { useEffect, useState, type FC } from 'react';

import { Button, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import {
  acceptableFacadeCandidateIds,
  countFacades,
  facadeIssuesOfPage,
  facadeReviewGroups,
  isFacadesJobActive,
} from '@/lib/cad/facades';
import type { ReviewFilter } from '@/lib/cad/sections';
import { jobLabel, jobTone } from '@/lib/cad/stages';

import { CadFacadesPage } from './CadFacadesPage';
import { CadReviewFilter } from './CadReviewFilter';
import type { IWorkspaceCadFacades } from './types';

/**
 * Вкладка «Фасады» (ADR-0048): сводка приёмки, один список видов (сначала открытый лист, затем
 * остальные страницы) и решения человека; первый запуск разбора - наверху, повторный - внизу.
 * Страницы не выбираются: генератор сам находит листы с заголовком фасада.
 */
export const CadFacadesPanel: FC<IWorkspaceCadFacades> = ({
  status,
  data,
  loadError,
  onReload,
  pageIndex = null,
  starting,
  onStart,
  deciding,
  onDecide,
  actionError,
  activeViewId,
  onSelectView,
  onPanelShown,
  onOpenPage,
}) => {
  const [filter, setFilter] = useState<ReviewFilter>('all');

  // Разметка на листе рисуется, только пока вкладка «Фасады» открыта.
  useEffect(() => {
    onPanelShown(true);
    return () => onPanelShown(false);
  }, [onPanelShown]);

  if (status === 'loading') {
    return (
      <div role="status" aria-label="Загрузка фасадов">
        <SkeletonRows rows={3} />
      </div>
    );
  }
  if (status === 'error' || data === null) {
    return (
      <ErrorState
        title="Фасады не загружены"
        description={loadError ?? undefined}
        onRetry={onReload}
      />
    );
  }

  const { job } = data;
  const jobActive = isFacadesJobActive(job?.status);
  const running = starting || jobActive;
  const hasResult = data.result_job_id !== null;
  const groups = facadeReviewGroups(data.views, pageIndex, filter);
  const acceptable = acceptableFacadeCandidateIds(data.views);
  const common = data.issues.filter((issue) => issue.page_index === null);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="cad-facades">
      {!hasResult && (
        <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <Button
            variant="primary"
            loading={running}
            onClick={onStart}
            className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
          >
            Разобрать фасады
          </Button>
          <p className="text-xs text-muted">
            Фасады ещё не разбирались: запустите разбор, результат появится здесь.
          </p>
        </div>
      )}

      {/* Статус задания - только пока оно идёт или упало: успешное завершение места не занимает. */}
      {job !== null && (jobActive || job.status === 'failed') && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]" role="status" aria-live="polite">
          <span className="flex flex-wrap items-center gap-[var(--s-3)]">
            <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
            <span className="mono text-xs text-muted">попытка {job.attempt}</span>
          </span>
          {jobActive && (
            <p className="text-xs text-muted">Фасады разбираются. Список обновится сам.</p>
          )}
          {job.status === 'failed' && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {job.error_code ? cadCodeText(job.error_code) : 'Фасады не разобраны.'}
              {job.error_message ? ` ${job.error_message}` : ''}
            </p>
          )}
        </div>
      )}

      {hasResult && data.views.length > 0 && (
        <CadReviewFilter
          label="Фильтр видов"
          counts={countFacades(data.views)}
          filter={filter}
          onFilterChange={setFilter}
          acceptableCount={acceptable.length}
          onAcceptAll={() => onDecide(acceptable, 'accept')}
          busy={deciding}
        />
      )}
      {actionError !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {actionError}
        </p>
      )}

      {hasResult && data.views.length === 0 && (
        <p className="text-xs text-muted">Виды фасадов в ревизии не найдены.</p>
      )}
      {hasResult && data.views.length > 0 && groups.length === 0 && (
        <p className="text-xs text-muted">С таким статусом видов нет.</p>
      )}
      {hasResult &&
        groups.map((group) => (
          <CadFacadesPage
            key={group.pageIndex}
            pageIndex={group.pageIndex}
            current={group.current}
            views={group.views}
            issues={facadeIssuesOfPage(data.issues, group.pageIndex)}
            busy={deciding}
            activeViewId={activeViewId}
            onSelectView={onSelectView}
            onOpenPage={onOpenPage}
            onDecide={onDecide}
          />
        ))}

      {common.length > 0 && (
        <details aria-label="Замечания задания" className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <summary className="min-h-[32px] cursor-pointer content-center text-micro font-semibold tracking-[0.06em] text-muted uppercase max-md:min-h-[44px]">
            Замечания задания ({common.length})
          </summary>
          <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
            {common.map((issue, index) => (
              <li
                key={`${issue.code}:${index}`}
                className="text-xs text-danger [overflow-wrap:anywhere]"
              >
                {issue.message}
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Повторный запуск - редкое действие: внизу и вторичной кнопкой. */}
      {hasResult && (
        <Button compact loading={running} onClick={onStart} className="self-start max-md:h-[44px]">
          Разобрать заново
        </Button>
      )}
    </div>
  );
};
