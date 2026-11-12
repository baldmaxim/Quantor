'use client';

import type { FC } from 'react';

import type { IWorkspaceCadSectionsLink } from '@/components/workspace/cad/types';
import { Button } from '@/components/ui';
import { cadCodeText } from '@/lib/cad/errors';
import {
  countLevels,
  isSectionsJobActive,
  sectionPageLabel,
  sectionPageRows,
} from '@/lib/cad/sections';

/**
 * Блок «Высота из разрезов» в запуске трасс: уровней и страниц-разрезов документа, переход на
 * страницу-разрез (решения по уровням принимают только там) и запуск распознавания, если его
 * ещё не было. Распознавание одно на всю ревизию, не на лист.
 */
export const CadMepSectionsLink: FC<IWorkspaceCadSectionsLink> = ({
  status,
  data,
  starting,
  onStart,
  onOpenPage,
  actionError,
}) => {
  if (status === 'loading' || data === null) {
    return (
      <p className="text-xs text-muted" role="status">
        {status === 'error' ? 'Разрезы не загружены.' : 'Загрузка разрезов…'}
      </p>
    );
  }

  const { job } = data;
  const running = starting || isSectionsJobActive(job?.status);
  const failed = job?.status === 'failed';
  const rows = sectionPageRows(data.pages, data.levels);
  const total = countLevels(data.levels);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]" data-testid="mep-sections-link">
      <h4 className="m-0 text-xs font-medium text-text">Высота из разрезов</h4>
      {running && (
        <p className="text-xs text-muted" role="status" aria-live="polite">
          Разрезы распознаются…
        </p>
      )}
      {failed && !running && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {job.error_code ? cadCodeText(job.error_code) : 'Разрезы не распознаны.'}
          {job.error_message ? ` ${job.error_message}` : ''}
        </p>
      )}
      {actionError !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {actionError}
        </p>
      )}

      {data.result_job_id === null ? (
        <>
          {!running && <p className="text-xs text-muted">Разрезы ещё не распознавались</p>}
          <Button
            loading={running}
            onClick={onStart}
            className="self-start max-md:h-[44px] max-md:w-full"
          >
            Распознать разрезы в документе
          </Button>
        </>
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted">Разрезы в документе не найдены.</p>
      ) : (
        <>
          <p className="text-xs text-muted">
            Уровней: принято <span className="tabular text-text">{total.accepted}</span>, кандидатов{' '}
            <span className="tabular text-text">{total.candidate}</span>, отклонено{' '}
            <span className="tabular text-text">{total.rejected}</span>
          </p>
          <ul
            className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0"
            aria-label="Страницы-разрезы"
          >
            {rows.map(({ page, counts }) => (
              <li key={page.page_index}>
                <Button
                  compact
                  onClick={() => onOpenPage(page.page_index)}
                  className="min-h-[44px] w-full !justify-between !whitespace-normal text-left max-md:h-auto"
                >
                  <span className="min-w-0 [overflow-wrap:anywhere]">
                    {sectionPageLabel(page)} — принято {counts.accepted}/{counts.total} →
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};
