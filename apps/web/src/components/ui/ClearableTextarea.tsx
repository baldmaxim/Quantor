'use client';

import { cx } from '@quantor/ui';
import { useRef, type TextareaHTMLAttributes } from 'react';

/**
 * Многострочное поле с крестиком «Очистить»: те же правила, что у `ClearableInput`. Крестик виден
 * только у непустого поля, не у `disabled` и `readOnly`; после очистки фокус остаётся в поле;
 * шрифт ввода на телефоне 16 px, тап-цель 44 px.
 */

interface IClearableTextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Имя поля для программ чтения и подсказки крестика: «Очистить: Подпись». */
  label: string;
  onClear: () => void;
  wrapperClassName?: string;
}

export const ClearableTextarea = ({
  label,
  onClear,
  wrapperClassName,
  className,
  ...input
}: IClearableTextareaProps) => {
  const field = useRef<HTMLTextAreaElement>(null);
  const filled = String(input.value ?? '').length > 0;
  const showClear = filled && !input.disabled && !input.readOnly;

  return (
    <span className={cx('relative inline-flex', wrapperClassName)}>
      <textarea
        ref={field}
        aria-label={label}
        {...input}
        className={cx(
          'min-h-[72px] w-full resize-y rounded-[var(--radius-sm)] border border-border-control bg-surface py-[var(--s-3)] pl-[var(--s-4)] text-base text-text md:text-sm',
          'placeholder:text-muted disabled:opacity-60',
          showClear ? 'pr-[calc(var(--s-6)+var(--s-5))]' : 'pr-[var(--s-4)]',
          className,
        )}
      />
      {showClear && (
        <button
          type="button"
          aria-label={`Очистить: ${label}`}
          onClick={() => {
            onClear();
            field.current?.focus();
          }}
          className="press absolute top-[var(--s-2)] right-[var(--s-2)] grid h-[28px] w-[28px] place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text max-md:h-[44px] max-md:w-[44px]"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-[12px] w-[12px]"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}
    </span>
  );
};
