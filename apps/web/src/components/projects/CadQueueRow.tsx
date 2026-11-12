import type { CadQueueItemRead } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import {
  queueErrorText,
  queueJobLabel,
  queuePagesText,
  queueStatusView,
} from '@/lib/cad/queue-view';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

/**
 * Строка очереди CAD: тип задания, документ и лист, статус, попытка и причина ошибки. Ведёт на
 * лист в рабочей области, если известны ревизия и страница. Узкий экран - колонкой.
 */

export interface ICadQueueRowProps {
  readonly projectId: string;
  readonly item: CadQueueItemRead;
}

const ROW =
  'flex min-h-[44px] min-w-0 flex-col gap-[var(--s-2)] px-[var(--s-6)] py-[var(--s-3)] transition-colors';
const ROW_LINK = `${ROW} hover:bg-surface-muted focus-visible:bg-surface-muted motion-reduce:transition-none`;

/** Адрес листа: позиция в рабочей области обычно равна индексу страницы + 1. */
const hrefOf = (projectId: string, item: CadQueueItemRead): string | null => {
  const page = item.pages[0];
  if (item.revision_id === null || page === undefined) return null;
  return workspaceCadHref(projectId, {
    revision: item.revision_id,
    position: page + 1,
    job: null,
    view: null,
  });
};

export const CadQueueRow: FC<ICadQueueRowProps> = ({ projectId, item }) => {
  const status = queueStatusView(item);
  const error = queueErrorText(item);
  const pages = queuePagesText(item.pages);
  const href = hrefOf(projectId, item);

  const content = (
    <>
      <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-2)]">
        <span className="text-sm font-medium">{queueJobLabel(item.job_type)}</span>
        <StatusBadge tone={status.tone} wrap>
          {status.label}
        </StatusBadge>
        {item.attempt > 1 && (
          <span className="mono text-xs text-muted">
            попытка {item.attempt}/{item.max_attempts}
          </span>
        )}
      </div>
      {(item.document_name !== null || pages !== null) && (
        <p className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
          {[item.document_name, pages].filter((part) => part !== null).join(' · ')}
        </p>
      )}
      {error && <p className="m-0 text-xs text-danger [overflow-wrap:anywhere]">{error}</p>}
    </>
  );

  return (
    <li className="border-b border-border last:border-b-0">
      {href ? (
        <Link href={href} className={ROW_LINK}>
          {content}
        </Link>
      ) : (
        <div className={ROW}>{content}</div>
      )}
    </li>
  );
};
