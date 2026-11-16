'use client';

import type { SectionIssueRead, SectionLevelRead, SectionPageRead } from '@quantor/api-client';
import { useState, type FC, type ReactNode } from 'react';

import {
  acceptableCandidateIds,
  autoAcceptedCount,
  countLevels,
  filterCutGroups,
  groupLevelsByCut,
  type ReviewFilter,
} from '@/lib/cad/sections';

import { CadReviewFilter } from './CadReviewFilter';
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
  /** Под сводкой: отказ последнего действия и флажок разметки. */
  underSummary?: ReactNode;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

/**
 * Разрез на открытом листе: заголовок, сводка приёмки с фильтром, один список уровней, замечания.
 *
 * Список один и в постоянном порядке: группы по линии разреза, внутри - сверху вниз по отметке,
 * как этажи на листе. После решения строка остаётся на месте - меняется только её статус. Уровень,
 * разложенный по отметкам точно, система принимает сама (ADR-0050): он в том же списке с бейджем
 * «Авто».
 */
export const CadSectionsPage: FC<ICadSectionsPageProps> = ({
  page,
  levels,
  issues,
  busy,
  activeLevelId,
  onSelectLevel,
  onDecide,
  underSummary = null,
}) => {
  const [filter, setFilter] = useState<ReviewFilter>('all');
  const acceptable = acceptableCandidateIds(levels);
  const allGroups = groupLevelsByCut(levels);
  const groups = filterCutGroups(allGroups, filter);
  const auto = autoAcceptedCount(levels);
  const place = [
    page.corps ? `корпус ${page.corps}` : null,
    page.section ? `секция ${page.section}` : null,
  ].filter((part): part is string => part !== null);

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

      {levels.length > 0 && (
        <CadReviewFilter
          label="Фильтр уровней"
          counts={countLevels(levels)}
          filter={filter}
          onFilterChange={setFilter}
          acceptableCount={acceptable.length}
          onAcceptAll={() => onDecide(acceptable, 'accept')}
          busy={busy}
          note={auto > 0 ? `принято автоматически: ${auto}` : null}
        />
      )}
      {underSummary}

      {levels.length === 0 ? (
        <p className="text-xs text-muted">На этой странице уровни не найдены.</p>
      ) : (
        <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <p className="text-micro text-muted">Сверху вниз, как на листе</p>
          {groups.length === 0 && (
            <p className="text-xs text-muted">С таким статусом уровней нет.</p>
          )}
          {groups.map((group) => (
            <section
              key={group.cut ?? ''}
              aria-label={group.label}
              className="flex min-w-0 flex-col gap-[var(--s-2)]"
            >
              {allGroups.length > 1 && <h5 className={HEADING}>{group.label}</h5>}
              <ul className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0">
                {group.levels.map((level) => (
                  <CadSectionLevelRow
                    key={level.id}
                    level={level}
                    active={level.id === activeLevelId}
                    busy={busy}
                    onSelect={onSelectLevel}
                    onDecide={onDecide}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
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
