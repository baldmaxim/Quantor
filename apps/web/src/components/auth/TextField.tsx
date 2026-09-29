import type { InputHTMLAttributes } from 'react';

import { cx } from '@/components/ui';

/**
 * Поле формы входа: подпись над полем и поле во всю ширину.
 *
 * Высота поля — тап-цель 44px на телефоне; размер шрифта полей на телефоне поднимает
 * до 16px базовая таблица стилей, иначе Safari зумил бы форму при фокусе.
 */

interface ITextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

export const TextField = ({ label, hint, className, ...input }: ITextFieldProps) => (
  <label className="flex flex-col gap-[var(--s-3)]">
    <span className="text-sm">{label}</span>
    <input
      {...input}
      className={cx(
        'h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-5)] text-sm text-text placeholder:text-muted disabled:opacity-60 max-md:h-[44px]',
        className,
      )}
    />
    {hint && <span className="text-xs text-muted">{hint}</span>}
  </label>
);
