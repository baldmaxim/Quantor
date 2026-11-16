'use client';

import { cx } from '@quantor/ui';
import type { FC } from 'react';

const WINDOW_LEGEND: readonly { readonly label: string; readonly className: string }[] = [
  // Как в сцене: кладка, осветлённая на 40% к белому; стекло - токен слоя 9 с прозрачностью 0.5 / 0.22.
  { label: 'Подоконная часть', className: 'bg-[color-mix(in_srgb,var(--cad-construction-masonry)_60%,white)]' },
  { label: 'Окно по фасаду', className: 'bg-[var(--cad-layer-9)]/50' },
];

const CANDIDATE_WINDOW_LEGEND = {
  label: 'Окно — кандидат (вид фасада не принят)',
  className: 'bg-[var(--cad-layer-9)]/20',
} as const;

const LEGEND: readonly { readonly label: string; readonly className: string }[] = [
  { label: 'Плита', className: 'bg-border-strong' },
  { label: 'Кладка', className: 'bg-[var(--cad-construction-masonry)]' },
  { label: 'Монолит', className: 'bg-[var(--cad-construction-monolith)]' },
  // Цвет как у кладки (так же в 2D): перегородка отличается штрихом, отдельного токена нет.
  { label: 'Перегородки ГКЛ', className: 'bg-[var(--cad-construction-masonry)]' },
  { label: 'Перемычки', className: 'bg-[var(--cad-construction-check)]' },
  { label: 'Двери', className: 'bg-[var(--cad-layer-6)]' },
  { label: 'Отверстие (кандидат)', className: 'bg-danger' },
  { label: 'Отверстие (включено)', className: 'bg-success' },
  { label: 'Не отверстие', className: 'bg-[var(--muted)]' },
];

interface ICadFloor3dLegendProps {
  /** В модели есть окна по фасаду. */
  readonly hasWindows?: boolean;
  /** Среди окон есть кандидаты (вид фасада не принят). */
  readonly hasCandidateWindows?: boolean;
}

/** Условные обозначения 3D-вида этажа: цвета категорий конструкций и отверстий плиты. */
export const CadFloor3dLegend: FC<ICadFloor3dLegendProps> = ({
  hasWindows = false,
  hasCandidateWindows = false,
}) => {
  const items = [
    ...LEGEND,
    ...(hasWindows ? WINDOW_LEGEND : []),
    ...(hasCandidateWindows ? [CANDIDATE_WINDOW_LEGEND] : []),
  ];
  return (
  <ul
    aria-label="Условные обозначения"
    className="pointer-events-none absolute bottom-[var(--s-4)] left-[var(--s-4)] flex max-w-[calc(100%-16px)] flex-wrap gap-x-[var(--s-4)] gap-y-[var(--s-2)] rounded-[var(--radius-sm)] bg-surface/80 px-[var(--s-3)] py-[var(--s-2)] text-xs"
  >
    {items.map((item) => (
      <li key={item.label} className="flex items-center gap-[var(--s-2)]">
        <span aria-hidden="true" className={cx('h-[10px] w-[10px] rounded-[2px]', item.className)} />
        {item.label}
      </li>
    ))}
  </ul>
  );
};
