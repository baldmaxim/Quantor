'use client';

import Link from 'next/link';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

import type { IStageRow } from './aiPipelineView';

/** Листы раскрытого этапа: название, статус, пояснение и ссылка в рабочую область листа. */

export interface IAiStageSheetListProps {
  readonly projectId: string;
  readonly stageTitle: string;
  readonly rows: readonly IStageRow[];
}

export const AiStageSheetList: FC<IAiStageSheetListProps> = ({ projectId, stageTitle, rows }) => {
  if (rows.length === 0) {
    return <p className="m-0 px-[var(--s-6)] py-[var(--s-4)] text-sm text-muted">Листов нет.</p>;
  }
  const viewsOfSheet = new Map<string, number>();
  for (const { row } of rows) {
    const key = `${row.revision_id}:${row.page_index}`;
    viewsOfSheet.set(key, (viewsOfSheet.get(key) ?? 0) + 1);
  }
  return (
    <ul
      aria-label={`Листы этапа «${stageTitle}»`}
      className="m-0 max-h-[40dvh] list-none overflow-y-auto overscroll-contain p-0"
    >
      {rows.map(({ row, view }) => {
        const key = `${row.revision_id}:${row.page_index}`;
        const several = (viewsOfSheet.get(key) ?? 0) > 1;
        const name = row.sheet_title || `Лист ${row.page_index + 1}`;
        const href = workspaceCadHref(projectId, {
          revision: row.revision_id,
          position: row.sheet_position,
          job: row.convert_job_id,
          view: row.view,
        });
        return (
          <li
            key={`${key}:${row.view ?? 'x'}`}
            className="flex flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)] border-t border-border px-[var(--s-6)] py-[var(--s-2)]"
          >
            <div className="min-w-0 flex-1 basis-[180px]">
              <p className="m-0 text-sm [overflow-wrap:anywhere]">
                {name}
                {several && row.view !== null ? ` · вид ${row.view}` : ''}
              </p>
              <p className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
                {row.document_name}
                {view.detail ? ` · ${view.detail}` : ''}
              </p>
            </div>
            <StatusBadge tone={view.badge.tone}>{view.badge.label}</StatusBadge>
            <Link
              href={href}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center text-xs text-accent hover:underline focus-visible:underline"
            >
              Открыть
            </Link>
          </li>
        );
      })}
    </ul>
  );
};
