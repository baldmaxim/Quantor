'use client';

import {
  readCadScaleNeeded,
  type CadScaleNeededItem,
  type CadScaleNeededRead,
} from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { workspaceCadHref } from '@/lib/cad/workspace-url';
import { unwrap } from '@/lib/queries';

/**
 * Листы CAD проекта, которым нужен масштаб: человек откалибровывает их вручную в рабочей области.
 * Масштаб здесь не определяется - только список и ссылка на лист.
 */

const SCALE_NEEDED_POLL_MS = 300_000;
const FIRST_COUNT = 10;

const REASONS: Record<CadScaleNeededItem['reason'], string> = {
  auto_scale_unconfirmed: 'Автомасштаб не подтверждён',
  scale_missing: 'Нет масштаба для зон и трасс',
  rerun_needed: 'Откалиброван — запустите преобразование',
};

export const cadScaleNeededKey = (projectId: string) => ['cad', projectId, 'scale-needed'] as const;

export const useCadScaleNeeded = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadScaleNeededRead> =>
  useQuery({
    queryKey: cadScaleNeededKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCadScaleNeeded({ throwOnError: true, path: { project_id: projectId } })),
    staleTime: SCALE_NEEDED_POLL_MS,
    refetchInterval: SCALE_NEEDED_POLL_MS,
  });

/** Позиция листа в рабочей области — с 1 (считает сервер); индекс страницы PDF — с 0. */
const hrefOf = (projectId: string, item: CadScaleNeededItem): string => {
  const view = item.view === null ? null : Number(item.view);
  return workspaceCadHref(projectId, {
    revision: item.revision_id,
    position: item.sheet_position ?? item.page_index + 1,
    job: item.convert_job_id,
    view: view !== null && Number.isInteger(view) ? view : null,
  });
};

export interface ICadScaleNeededCardProps {
  readonly projectId: string;
}

export const CadScaleNeededCard: FC<ICadScaleNeededCardProps> = ({ projectId }) => {
  const query = useCadScaleNeeded(projectId, true);
  const [expanded, setExpanded] = useState(false);
  const data = query.data;

  if (query.isError) {
    return (
      <div
        role="alert"
        className="mb-[var(--s-4)] flex flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-6)] py-[var(--s-3)]"
      >
        <span className="min-w-0 flex-1 text-xs text-danger">
          Не удалось получить список листов без масштаба
        </span>
        <Button compact onClick={() => void query.refetch()}>
          Повторить
        </Button>
      </div>
    );
  }
  if (!data || data.total === 0) return null;

  const items = expanded ? data.items : data.items.slice(0, FIRST_COUNT);

  return (
    <section
      aria-label="Нужен масштаб"
      className="mb-[var(--s-4)] min-w-0 shrink-0 overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface"
    >
      <h2 className="m-0 border-b border-border px-[var(--s-6)] py-[var(--s-3)] text-sm font-medium">
        Нужен масштаб: {data.total}
      </h2>
      <ul
        aria-label="Листы без масштаба"
        className="m-0 max-h-48 list-none overflow-y-auto overscroll-contain p-0"
      >
        {items.map((item) => (
          <li
            key={`${item.revision_id}:${item.page_index}`}
            className="flex min-w-0 flex-wrap items-center justify-between gap-x-[var(--s-4)] border-b border-border px-[var(--s-6)] py-[var(--s-2)] last:border-b-0"
          >
            <div className="min-w-0 flex-1 text-xs [overflow-wrap:anywhere]">
              <p className="m-0 text-text">
                {item.document_title} · {item.page_label ?? `стр. ${item.page_index + 1}`}
              </p>
              <p className="m-0 text-muted">{REASONS[item.reason]}</p>
            </div>
            <Link
              href={hrefOf(projectId, item)}
              className="flex min-h-[44px] items-center text-xs text-accent hover:underline focus-visible:underline"
            >
              Откалибровать
            </Link>
          </li>
        ))}
      </ul>
      {!expanded && data.total > FIRST_COUNT && (
        <div className="border-t border-border px-[var(--s-6)] py-[var(--s-2)]">
          <Button compact onClick={() => setExpanded(true)}>
            Показать все ({data.total})
          </Button>
        </div>
      )}
    </section>
  );
};
