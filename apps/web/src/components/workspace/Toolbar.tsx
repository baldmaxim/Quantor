'use client';

import type { ReactNode } from 'react';

import { cx } from '@/components/ui';

/**
 * Панель инструментов рабочей области.
 *
 * Кнопки без подписи обязаны иметь подсказку и доступное имя: иконка «рука» без
 * пояснения ничего не значит для того, кто открыл портал впервые.
 */

interface IToolButtonProps {
  label: string;
  hint?: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: ReactNode;
  /** Кнопка с текстом, а не только с иконкой. */
  wide?: boolean;
}

export const ToolButton = ({
  label,
  hint,
  active = false,
  disabled = false,
  onClick,
  children,
  wide = false,
}: IToolButtonProps) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    // Выключенный переключатель состояние не теряет: «слой распознавания
    // включён, но сейчас недоступен» — это не то же самое, что «выключен».
    aria-pressed={onClick ? active : undefined}
    aria-label={label}
    title={hint ? `${label} — ${hint}` : label}
    className={cx(
      // flex-none обязателен: строка панели узкая, и без него кнопка сжимается,
      // подпись переносится на вторую строку и обрезается по высоте ряда.
      // press, а не transition-colors: это самая нажимаемая кнопка продукта, и
      // отдача у неё должна быть та же, что у обычной.
      'press h-[var(--h-ctl-ws)] flex-none rounded-[var(--radius-sm)]',
      // grid и flex вместе давали бы конфликт display: раскладка выбирается одна.
      wide
        ? 'flex items-center gap-[var(--s-3)] px-[var(--s-4)] text-xs whitespace-nowrap'
        : 'grid w-[30px] place-items-center',
      active ? 'bg-accent-soft text-accent' : 'text-muted',
      !disabled && !active && 'hover:bg-surface-muted hover:text-text active:bg-surface-sunken',
      // 45%, как у Button: разные значения у соседних кнопок читаются как разное
      // состояние, хотя состояние одно.
      disabled && 'cursor-not-allowed opacity-45',
    )}
  >
    {children}
  </button>
);

export const ToolDivider = () => (
  <span aria-hidden="true" className="mx-[var(--s-3)] h-[18px] w-px flex-none bg-border" />
);

/** Числовое поле панели инструментов: номер листа, масштаб. */
export const ToolField = ({
  value,
  suffix,
  label,
}: {
  value: ReactNode;
  suffix?: ReactNode;
  label: string;
}) => (
  <span
    className="flex flex-none items-center gap-[var(--s-2)] text-xs whitespace-nowrap text-muted"
    aria-label={label}
  >
    <span className="mono rounded-[var(--radius-xs)] border border-border-control bg-surface-sunken px-[var(--s-3)] py-[1px] text-text">
      {value}
    </span>
    {suffix}
  </span>
);
