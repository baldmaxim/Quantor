'use client';

import type { FC } from 'react';

import { Button, SegmentedControl, type ISegmentedOption } from '@/components/ui';
import type { ISectionCounts, ReviewFilter } from '@/lib/cad/sections';

interface ICadReviewFilterProps {
  /** Доступное имя фильтра: «Фильтр уровней», «Фильтр видов». */
  label: string;
  counts: ISectionCounts;
  filter: ReviewFilter;
  onFilterChange: (filter: ReviewFilter) => void;
  /** Сколько кандидатов можно принять разом; 0 - кнопки «Принять все» нет. */
  acceptableCount: number;
  onAcceptAll: () => void;
  busy: boolean;
  /** Дополнение к сводке, например «принято автоматически: 3». */
  note?: string | null;
}

/**
 * Сводка приёмки и фильтр по статусу - общие для разделов «Разрезы» и «Фасады».
 *
 * Сводка отвечает на вопрос «сколько осталось»; фильтр только скрывает строки списка - порядок и
 * группы не меняются, поэтому строка после решения остаётся на своём месте.
 */
export const CadReviewFilter: FC<ICadReviewFilterProps> = ({
  label,
  counts,
  filter,
  onFilterChange,
  acceptableCount,
  onAcceptAll,
  busy,
  note = null,
}) => {
  const options: readonly ISegmentedOption<ReviewFilter>[] = [
    { value: 'all', label: `Все ${counts.total}` },
    { value: 'candidate', label: `Проверить ${counts.candidate}`, disabled: counts.candidate === 0 },
    { value: 'accepted', label: `Принято ${counts.accepted}`, disabled: counts.accepted === 0 },
    { value: 'rejected', label: `Отклонено ${counts.rejected}`, disabled: counts.rejected === 0 },
  ];
  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
      <div className="flex min-w-0 flex-wrap items-center gap-[var(--s-2)]">
        <p
          className="min-w-0 flex-1 text-xs [overflow-wrap:anywhere]"
          data-testid="review-summary"
          aria-live="polite"
        >
          <span className="font-medium">
            {counts.candidate === 0
              ? 'Все решения приняты'
              : `Осталось проверить: ${counts.candidate} из ${counts.total}`}
          </span>
          {note !== null && note !== '' && <span className="text-muted"> · {note}</span>}
        </p>
        {acceptableCount > 0 && (
          <Button
            compact
            variant="primary"
            className="shrink-0 max-md:h-[44px]"
            disabled={busy}
            onClick={onAcceptAll}
          >
            Принять все ({acceptableCount})
          </Button>
        )}
      </div>
      <SegmentedControl
        label={label}
        layout="wrap"
        compact
        value={filter}
        onChange={onFilterChange}
        options={options}
        className="gap-[var(--s-2)] max-md:[&>button]:h-[44px]"
      />
    </div>
  );
};
