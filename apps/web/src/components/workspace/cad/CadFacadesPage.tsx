'use client';

import type { FacadeIssueRead, FacadeViewRead } from '@quantor/api-client';
import type { FC } from 'react';

import { CadFacadeViewRow } from './CadFacadeViewRow';
import type { IWorkspaceCadFacades } from './types';

interface ICadFacadesPageProps {
  pageIndex: number;
  views: readonly FacadeViewRead[];
  issues: readonly FacadeIssueRead[];
  busy: boolean;
  activeViewId: string | null;
  onSelectView: IWorkspaceCadFacades['onSelectView'];
  onOpenPage: IWorkspaceCadFacades['onOpenPage'];
  onDecide: IWorkspaceCadFacades['onDecide'];
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

/** Страница с фасадами: виды страницы и замечания генератора по ней. */
export const CadFacadesPage: FC<ICadFacadesPageProps> = ({
  pageIndex,
  views,
  issues,
  busy,
  activeViewId,
  onSelectView,
  onOpenPage,
  onDecide,
}) => (
  <section
    aria-label={`Страница ${pageIndex + 1}`}
    className="flex min-w-0 flex-col gap-[var(--s-2)]"
    data-testid="facades-page"
  >
    <h4 className={HEADING}>Стр. {pageIndex + 1}</h4>
    <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
      {views.map((view) => (
        <CadFacadeViewRow
          key={view.id}
          view={view}
          busy={busy}
          active={view.id === activeViewId}
          onSelect={onSelectView}
          onOpenPage={onOpenPage}
          onDecide={onDecide}
        />
      ))}
    </ul>
    {issues.length > 0 && (
      <details aria-label="Замечания страницы" className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <summary
          className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}
        >
          Замечания страницы ({issues.length})
        </summary>
        <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
          {issues.map((issue, index) => (
            <li key={`${issue.code}:${index}`} className="text-xs text-danger [overflow-wrap:anywhere]">
              {issue.message}
            </li>
          ))}
        </ul>
      </details>
    )}
  </section>
);
