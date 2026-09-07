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
    aria-pressed={onClick && !disabled ? active : undefined}
    aria-label={label}
    title={hint ? `${label} — ${hint}` : label}
    className={cx(
      // flex-none обязателен: строка панели узкая, и без него кнопка сжимается,
      // подпись переносится на вторую строку и обрезается по высоте ряда.
      'h-[var(--h-ctl-ws)] flex-none rounded-[var(--radius-sm)] transition-colors',
      // grid и flex вместе давали бы конфликт display: раскладка выбирается одна.
      wide
        ? 'flex items-center gap-[var(--s-3)] px-[var(--s-4)] text-xs whitespace-nowrap'
        : 'grid w-[30px] place-items-center',
      active ? 'bg-accent-soft text-accent' : 'text-muted',
      !disabled && !active && 'hover:bg-surface-muted hover:text-text',
      disabled && 'cursor-not-allowed opacity-40',
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
