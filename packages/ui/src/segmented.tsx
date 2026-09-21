/**
 * Сегментированный переключатель: единственный выбор из нескольких.
 *
 * Собран из четырёх копий, разошедшихся отдачей нажатия, рамкой и ориентиром для
 * программ чтения. Раскладка — параметр, потому что копии отличались именно ею:
 * ряд встык в шапке списка, сетка в узкой панели, чипы с переносом в опытах.
 *
 * Стрелочной навигации нет намеренно: это группа переключателей с `aria-pressed`,
 * а не `radiogroup`, — обход клавишей Tab здесь ожидаем. Вдобавок в рабочей
 * области стрелки заняты просмотрщиком.
 */

import type { ReactNode } from 'react';

import { cx } from './cx';

export type SegmentedLayout = 'row' | 'grid' | 'wrap';

export interface ISegmentedOption<T extends string | number> {
  value: T;
  label: ReactNode;
  /** Уходит в подсказку при наведении. */
  hint?: string;
  disabled?: boolean;
}

interface ISegmentedControlProps<T extends string | number> {
  /** Доступное имя группы: без него набор кнопок не читается как один выбор. */
  label: string;
  value: T;
  options: readonly ISegmentedOption<T>[];
  onChange: (value: T) => void;
  layout?: SegmentedLayout;
  compact?: boolean;
  className?: string;
}

const CONTAINERS: Record<SegmentedLayout, string> = {
  // Без рамки и дорожки: выбранный сегмент виден акцентом, а контур группы на
  // тёмной теме читался как белый прямоугольник.
  row: 'flex flex-none items-center gap-[2px] rounded-[var(--radius-sm)] p-[2px]',
  grid: 'grid grid-cols-2 gap-[var(--s-2)]',
  wrap: 'flex flex-wrap items-center gap-[var(--s-3)]',
};

const ITEMS: Record<SegmentedLayout, string> = {
  row: 'rounded-[calc(var(--radius-sm)-2px)]',
  grid: 'rounded-[var(--radius-sm)] border',
  wrap: 'rounded-full border px-[var(--s-5)]',
};

export const SegmentedControl = <T extends string | number>({
  label,
  value,
  options,
  onChange,
  layout = 'row',
  compact = false,
  className,
}: ISegmentedControlProps<T>) => (
  <div
    role="group"
    aria-label={label}
    className={cx(
      CONTAINERS[layout],
      // Тап-цель растит сегменты на телефоне; дорожка обязана расти вместе с ними.
      layout === 'row' && (compact ? 'h-[var(--h-ctl-ws)]' : 'h-[var(--h-ctl)] max-md:h-[44px]'),
      className,
    )}
  >
    {options.map((option) => {
      const active = option.value === value;

      return (
        <button
          key={String(option.value)}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={active}
          disabled={option.disabled}
          title={option.hint}
          className={cx(
            'press whitespace-nowrap',
            compact ? 'h-[var(--h-ctl-ws)] text-micro' : 'h-full text-sm',
            layout === 'row' && !compact && 'px-[var(--s-5)]',
            layout === 'grid' && 'px-[var(--s-3)]',
            ITEMS[layout],
            active
              ? cx(
                  'bg-accent-soft font-medium text-accent',
                  layout === 'row' ? '' : 'border-accent',
                )
              : cx(
                  'text-muted hover:bg-surface-muted hover:text-text',
                  layout === 'row' ? '' : 'border-border-control',
                ),
            option.disabled === true && 'cursor-not-allowed opacity-45',
          )}
        >
          {option.label}
        </button>
      );
    })}
  </div>
);
