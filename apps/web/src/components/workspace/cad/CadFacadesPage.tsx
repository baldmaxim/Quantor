'use client';

import type { FacadeIssueRead, FacadeViewRead } from '@quantor/api-client';
import type { FC } from 'react';

import { CadFacadeViewRow } from './CadFacadeViewRow';
import type { IWorkspaceCadFacades } from './types';

interface ICadFacadesPageProps {
  pageIndex: number;
  /** Группа открытого листа: заголовок «На этом листе», без перехода. */
  current: boolean;
  views: readonly FacadeViewRead[];
  issues: readonly FacadeIssueRead[];
  busy: boolean;
  activeViewId: string | null;
  onSelectView: IWorkspaceCadFacades['onSelectView'];
  onOpenPage: IWorkspaceCadFacades['onOpenPage'];
  onDecide: IWorkspaceCadFacades['onDecide'];
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

/**
 * Страница с фасадами: виды страницы и замечания генератора по ней. Заголовок чужой страницы -
 * кнопка перехода к ней; группа открытого листа подписана «На этом листе».
 */
export const CadFacadesPage: FC<ICadFacadesPageProps> = ({
  pageIndex,
  current,
  views,
  issues,
  busy,
  activeViewId,
  onSelectView,
  onOpenPage,
  onDecide,
}) => (
  <section
    aria-label={current ? 'На этом листе' : `Страница ${pageIndex + 1}`}
    data-current={current}
    className="flex min-w-0 flex-col gap-[var(--s-2)]"
    data-testid="facades-page"
  >
    {current ? (
      <h4 className={HEADING}>На этом листе</h4>
    ) : (
      <h4 className={HEADING}>
        <button
          type="button"
          title="Открыть страницу"
          onClick={() => onOpenPage(pageIndex)}
          className="min-h-[32px] cursor-pointer text-left tracking-[inherit] uppercase underline-offset-2 hover:text-text hover:underline max-md:min-h-[44px] max-md:min-w-[44px]"
        >
          Стр. {pageIndex + 1}
        </button>
      </h4>
    )}
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
