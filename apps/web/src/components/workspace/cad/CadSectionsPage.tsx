'use client';

import type { SectionIssueRead, SectionLevelRead, SectionPageRead } from '@quantor/api-client';
import type { FC, ReactNode } from 'react';

import { Button } from '@/components/ui';
import { acceptableCandidateIds, reviewBuckets } from '@/lib/cad/sections';

import { CadSectionLevelRow } from './CadSectionLevelRow';
import type { IWorkspaceCadSections } from './types';

interface ICadSectionsPageProps {
  page: SectionPageRead;
  levels: readonly SectionLevelRead[];
  issues: readonly SectionIssueRead[];
  busy: boolean;
  activeLevelId: string | null;
  onSelectLevel: IWorkspaceCadSections['onSelectLevel'];
  onDecide: IWorkspaceCadSections['onDecide'];
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

/**
 * Разрез на открытом листе: заголовок, сводка, уровни на проверку, принятые и отклонённые,
 * замечания генератора.
 *
 * Уровень, разложенный по отметкам точно и без разногласий, система принимает сама (ADR-0050):
 * человеку остаются только кандидаты - они наверху и раскрыты. Принятые и отклонённые свёрнуты.
 */
export const CadSectionsPage: FC<ICadSectionsPageProps> = ({
  page,
  levels,
  issues,
  busy,
  activeLevelId,
  onSelectLevel,
  onDecide,
}) => {
  const buckets = reviewBuckets(levels);
  const acceptable = acceptableCandidateIds(levels);
  const manyCuts = new Set(levels.map((level) => level.cut)).size > 1;
  const place = [
    page.corps ? `корпус ${page.corps}` : null,
    page.section ? `секция ${page.section}` : null,
  ].filter((part): part is string => part !== null);

  const list = (items: readonly SectionLevelRead[]): ReactNode => (
    <ul className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0">
      {items.map((level) => (
        <CadSectionLevelRow
          key={level.id}
          level={level}
          active={level.id === activeLevelId}
          busy={busy}
          showCut={manyCuts}
          onSelect={onSelectLevel}
          onDecide={onDecide}
        />
      ))}
    </ul>
  );

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="sections-page">
      <div className="flex min-w-0 flex-col gap-[var(--s-1)]">
        <h4 className="text-sm font-medium [overflow-wrap:anywhere]">
          {page.title?.trim() ? page.title : `Разрез, стр. ${page.page_index + 1}`}
        </h4>
        {(place.length > 0 || page.cuts.length > 0) && (
          <p className="text-xs text-muted [overflow-wrap:anywhere]">
            {[...place, page.cuts.length > 0 ? `разрезы: ${page.cuts.join(', ')}` : null]
              .filter((part): part is string => part !== null)
              .join(' · ')}
          </p>
        )}
      </div>

      {levels.length === 0 ? (
        <p className="text-xs text-muted">На этой странице уровни не найдены.</p>
      ) : (
        <>
          <p className="text-xs text-muted" data-testid="sections-review-summary">
            Принято автоматически: {buckets.auto} · на проверку: {buckets.review.length}
            {buckets.rejected.length > 0 ? ` · отклонено: ${buckets.rejected.length}` : ''}
          </p>

          <section aria-label="На проверку" className="flex min-w-0 flex-col gap-[var(--s-2)]">
            <div className="flex min-w-0 flex-wrap items-center gap-[var(--s-2)]">
              <h5 className={HEADING}>На проверку ({buckets.review.length})</h5>
              {acceptable.length > 0 && (
                <Button
                  compact
                  variant="primary"
                  className="ml-auto max-md:h-[44px]"
                  disabled={busy}
                  onClick={() => onDecide(acceptable, 'accept')}
                >
                  Принять все ({acceptable.length})
                </Button>
              )}
            </div>
            {buckets.review.length === 0 ? (
              <p className="text-xs text-muted">
                Разногласий нет: все уровни попали в отметки и приняты.
              </p>
            ) : (
              list(buckets.review)
            )}
          </section>

          {buckets.accepted.length > 0 && (
            <details className="flex min-w-0 flex-col gap-[var(--s-2)]">
              <summary
                className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}
              >
                Принято ({buckets.accepted.length})
              </summary>
              {list(buckets.accepted)}
            </details>
          )}

          {buckets.rejected.length > 0 && (
            <details className="flex min-w-0 flex-col gap-[var(--s-2)]">
              <summary
                className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}
              >
                Отклонено ({buckets.rejected.length})
              </summary>
              {list(buckets.rejected)}
            </details>
          )}
        </>
      )}

      {issues.length > 0 && (
        <details aria-label="Замечания страницы" className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <summary
            className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}
          >
            Замечания страницы ({issues.length})
          </summary>
          <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
            {issues.map((issue, index) => (
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
