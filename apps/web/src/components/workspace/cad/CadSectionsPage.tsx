'use client';

import type { SectionIssueRead, SectionLevelRead, SectionPageRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { acceptableCandidateIds, groupLevelsByCut } from '@/lib/cad/sections';

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

/** Разрез на открытом листе: заголовок, уровни по линиям разреза, замечания генератора. */
export const CadSectionsPage: FC<ICadSectionsPageProps> = ({
  page,
  levels,
  issues,
  busy,
  activeLevelId,
  onSelectLevel,
  onDecide,
}) => {
  const groups = groupLevelsByCut(levels);
  const acceptable = acceptableCandidateIds(levels);
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

      {levels.length === 0 ? (
        <p className="text-xs text-muted">На этой странице уровни не найдены.</p>
      ) : (
        <>
          <Button
            compact
            variant="primary"
            className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
            disabled={busy || acceptable.length === 0}
            onClick={() => onDecide(acceptable, 'accept')}
          >
            Принять все на листе{acceptable.length > 0 ? ` (${acceptable.length})` : ''}
          </Button>
          {groups.map((group) => (
            <section
              key={group.cut ?? '—'}
              aria-label={group.label}
              className="flex min-w-0 flex-col gap-[var(--s-2)]"
            >
              <h5 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                {group.label}
              </h5>
              <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
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
        </>
      )}

      {issues.length > 0 && (
        <section aria-label="Замечания страницы" className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <h5 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            Замечания страницы
          </h5>
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
        </section>
      )}
    </div>
  );
};
