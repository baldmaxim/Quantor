'use client';

import type { FC } from 'react';

import { Button } from '@/components/ui';

/** Пагинация по страницам фиксированного размера: «1–500 из 1 234». */

interface IPagerProps {
  readonly offset: number;
  readonly limit: number;
  readonly total: number;
  readonly onOffset: (offset: number) => void;
}

export const SheetPassportPager: FC<IPagerProps> = ({ offset, limit, total, onOffset }) => {
  if (total <= limit) {
    return null;
  }
  const to = Math.min(offset + limit, total);

  return (
    <nav aria-label="Страницы списка" className="flex flex-wrap items-center gap-[var(--s-4)]">
      <Button disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
        Назад
      </Button>
      <span className="tabular text-sm text-muted">
        {offset + 1}–{to} из {total}
      </span>
      <Button disabled={to >= total} onClick={() => onOffset(offset + limit)}>
        Вперёд
      </Button>
    </nav>
  );
};
