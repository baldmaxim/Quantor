'use client';

import { useEffect, type FC } from 'react';

import { Button, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import { facadeIssuesOfPage, groupFacadesByPage, isFacadesJobActive } from '@/lib/cad/facades';
import { jobLabel, jobTone } from '@/lib/cad/stages';

import { CadFacadesPage } from './CadFacadesPage';
import type { IWorkspaceCadFacades } from './types';

/**
 * Вкладка «Фасады» (ADR-0048): запуск разбора фасадов ревизии, виды по страницам и решения человека.
 * Страницы не выбираются: генератор сам находит листы с заголовком фасада.
 */
export const CadFacadesPanel: FC<IWorkspaceCadFacades> = ({
  status,
  data,
  loadError,
  onReload,
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
  const running = starting || isFacadesJobActive(job?.status);
  const groups = groupFacadesByPage(data.views);
  const common = data.issues.filter((issue) => issue.page_index === null);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="cad-facades">
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <Button
          variant="primary"
          loading={running}
          onClick={onStart}
          className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
        >
          {job === null ? 'Разобрать фасады' : 'Разобрать фасады заново'}
        </Button>
        {job !== null && (
          <div className="flex min-w-0 flex-col gap-[var(--s-2)]" role="status" aria-live="polite">
            <span className="flex flex-wrap items-center gap-[var(--s-3)]">
              <StatusBadge tone={jobTone(job.status)}>{jobLabel(job.status)}</StatusBadge>
              <span className="mono text-xs text-muted">попытка {job.attempt}</span>
            </span>
            {isFacadesJobActive(job.status) && (
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
        {actionError !== null && (
          <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
            {actionError}
          </p>
        )}
      </div>

      {data.result_job_id === null ? (
        <p className="text-xs text-muted">
          Фасады ещё не разбирались: запустите разбор, результат появится здесь.
        </p>
      ) : groups.length === 0 ? (
        <p className="text-xs text-muted">Виды фасадов в ревизии не найдены.</p>
      ) : (
        groups.map((group) => (
          <CadFacadesPage
            key={group.pageIndex}
            pageIndex={group.pageIndex}
            views={group.views}
            issues={facadeIssuesOfPage(data.issues, group.pageIndex)}
            busy={deciding}
            activeViewId={activeViewId}
            onSelectView={onSelectView}
            onOpenPage={onOpenPage}
            onDecide={onDecide}
          />
        ))
      )}

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
    </div>
  );
};
