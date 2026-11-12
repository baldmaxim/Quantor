'use client';

import type { SectionsRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { countLevels, sectionPageLabel, sectionPageRows } from '@/lib/cad/sections';

interface ICadSectionsSummaryProps {
  data: SectionsRead;
  onOpenPage: (pageIndex: number) => void;
}

/** Сводка по проекту, когда открытый лист - не разрез: счётчики и переход на страницы-разрезы. */
export const CadSectionsSummary: FC<ICadSectionsSummaryProps> = ({ data, onOpenPage }) => {
  const total = countLevels(data.levels);
  const rows = sectionPageRows(data.pages, data.levels);
  if (rows.length === 0) {
    return <p className="text-xs text-muted">Разрезы в документе не найдены.</p>;
  }
  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="sections-summary">
      <p className="text-xs text-muted">
        Открытый лист - не разрез. Уровней: принято{' '}
        <span className="tabular text-text">{total.accepted}</span>, кандидатов{' '}
        <span className="tabular text-text">{total.candidate}</span>, отклонено{' '}
        <span className="tabular text-text">{total.rejected}</span>.
      </p>
      <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0" aria-label="Страницы-разрезы">
        {rows.map(({ page, counts }) => (
          <li key={page.page_index}>
            <Button
              compact
              onClick={() => onOpenPage(page.page_index)}
              className="min-h-[44px] w-full !justify-between !whitespace-normal text-left max-md:h-auto"
            >
              <span className="min-w-0 [overflow-wrap:anywhere]">{sectionPageLabel(page)}</span>
              <span className="tabular shrink-0 text-muted">
                {counts.accepted}/{counts.total}
              </span>
            </Button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">В строке: принято / всего уровней страницы.</p>
    </div>
  );
};
