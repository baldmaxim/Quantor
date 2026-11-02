'use client';

import { cx } from '@quantor/ui';
import { useRef, type InputHTMLAttributes } from 'react';

/**
 * Текстовое поле с крестиком «Очистить».
 *
 * Крестик виден только у непустого поля, не у `disabled` и `readOnly`; текст под него не заходит.
 * Кнопка не отправляет форму, после очистки фокус остаётся в поле. Системный крестик
 * `type="search"` скрыт — остаётся один свой на все браузеры. Тап-цель на телефоне — 44 px,
 * шрифт ввода на телефоне 16 px: иначе Safari зумит форму при фокусе.
 */

interface IClearableInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Имя поля для программ чтения и подсказки крестика: «Очистить: Подпись». */
  label: string;
  /** Вызывается по крестику. Поле управляется снаружи, поэтому очищает его тоже владелец. */
  onClear: () => void;
  wrapperClassName?: string;
}

export const ClearableInput = ({
  label,
  onClear,
  wrapperClassName,
  className,
  ...input
}: IClearableInputProps) => {
  const field = useRef<HTMLInputElement>(null);
  const filled = String(input.value ?? '').length > 0;
  const showClear = filled && !input.disabled && !input.readOnly;

  return (
    <span className={cx('relative inline-flex items-center', wrapperClassName)}>
      <input
        ref={field}
        aria-label={label}
        {...input}
        className={cx(
          'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface text-base text-text md:text-sm',
          'pl-[var(--s-4)] placeholder:text-muted disabled:opacity-60 max-md:h-[44px]',
          // Место под крестик резервируется, пока он виден: текст не заходит под кнопку.
          showClear ? 'pr-[calc(var(--s-6)+var(--s-5))]' : 'pr-[var(--s-4)]',
          '[&::-webkit-search-cancel-button]:hidden',
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
          className="press absolute right-[var(--s-2)] grid h-[28px] w-[28px] place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text max-md:h-[44px] max-md:w-[44px]"
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
