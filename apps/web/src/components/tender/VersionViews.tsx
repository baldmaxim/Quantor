'use client';

import type { TenderViewInfoRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import type { FC } from 'react';

import { Button, EmptyState, StatusBadge } from '@/components/ui';
import { resolveSheetPosition } from '@/lib/cad/building3d-queries';
import { tenderSheetHref } from '@/lib/tender/present';

/**
 * Виды версии: документ-лист-этажи и переход в рабочую область CAD со слоем этой версии
 * (`tender=<calc_id>`) — планом и «3D этажа». Позиция листа в области считается по списку листов
 * ревизии, как у остальных ссылок на вид.
 */

interface IViewsProps {
  readonly projectId: string;
  readonly calcId: string;
  readonly views: readonly TenderViewInfoRead[];
}

export const VersionViews: FC<IViewsProps> = ({ projectId, calcId, views }) => {
  const router = useRouter();
  const client = useQueryClient();

  const open = async (view: TenderViewInfoRead, mode: 'plan' | '3d'): Promise<void> => {
    const position = await resolveSheetPosition(client, view.revision_id, view.page_index);
    router.push(
      tenderSheetHref(
        projectId,
        calcId,
        { revisionId: view.revision_id, pageIndex: view.page_index, view: view.view, position },
        mode,
      ),
    );
  };

  if (views.length === 0) return <EmptyState compact title="У версии нет геометрии" />;

  return (
    <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
      {views.map((view) => (
        <li
          key={view.view_key}
          className="flex flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-3)]"
        >
          <div className="flex min-w-0 flex-1 basis-[220px] flex-col gap-[var(--s-1)]">
            <span className="text-sm [overflow-wrap:anywhere]">
              Лист {view.page_index + 1}
              {view.view > 0 ? `, вид ${view.view + 1}` : ''} · этажи{' '}
              {view.floors.length > 0 ? view.floors.join(', ') : '—'}
            </span>
            <span className="tabular text-xs text-muted">
              трасс: {view.polylines} · элементов: {view.elements}
            </span>
          </div>
          {view.base_stale && <StatusBadge tone="warning">база устарела</StatusBadge>}
          <Button compact onClick={() => void open(view, 'plan')}>
            Открыть на листе
          </Button>
          <Button compact onClick={() => void open(view, '3d')}>
            3D этажа
          </Button>
        </li>
      ))}
    </ul>
  );
};
