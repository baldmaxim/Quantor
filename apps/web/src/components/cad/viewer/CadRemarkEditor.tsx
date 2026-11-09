'use client';

import { useEffect, useId, useRef, useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { MAX_COMMENT_LENGTH, REMARK_TYPES, type RemarkType } from '@/lib/cad/remarks';

import type { IRemarkDraft } from './useCadRemarks';

interface ICadRemarkEditorProps {
  /** Номер будущего замечания: в списке и на листе он тот же. */
  number: number;
  /** Запись на сервер идёт: «Сохранить» заблокирована, форма не теряет введённое. */
  saving?: boolean;
  onSave: (draft: IRemarkDraft) => void;
  onCancel: () => void;
}

const FIELD =
  'rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

/** Встроенная форма нового замечания: тип, комментарий, «Сохранить» и «Отмена». */
export const CadRemarkEditor: FC<ICadRemarkEditorProps> = ({
  number,
  saving = false,
  onSave,
  onCancel,
}) => {
  const baseId = useId();
  const [type, setType] = useState<RemarkType>('missing_wall');
  const [comment, setComment] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);
  const form = useRef<HTMLFormElement>(null);

  // Форма открывается под листом: на телефоне она ниже экрана, и её нужно показать.
  useEffect(() => {
    form.current?.scrollIntoView?.({ block: 'nearest' });
  }, []);

  return (
    <form
      ref={form}
      aria-label={`Новое замечание ${number}`}
      className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-accent bg-surface-muted p-[var(--s-5)]"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ type, comment: comment.trim() });
      }}
    >
      <h4 className="text-sm font-medium">Замечание {number}</h4>

      <label htmlFor={`${baseId}-type`} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">Тип</span>
        <select
          id={`${baseId}-type`}
          value={type}
          onChange={(event) => setType(event.target.value as RemarkType)}
          className={`${FIELD} h-[var(--h-ctl)] max-md:h-[44px]`}
        >
          {REMARK_TYPES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-[var(--s-2)]">
        <label htmlFor={`${baseId}-comment`} className="text-sm">
          Комментарий
        </label>
        <span className="relative flex">
          <textarea
            ref={field}
            id={`${baseId}-comment`}
            rows={3}
            maxLength={MAX_COMMENT_LENGTH}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            className={`${FIELD} w-full py-[var(--s-3)] pr-[calc(var(--s-6)+var(--s-5))]`}
          />
          {comment.length > 0 && (
            <button
              type="button"
              aria-label="Очистить: Комментарий"
              onClick={() => {
                setComment('');
                field.current?.focus();
              }}
              className="press absolute top-0 right-[var(--s-2)] grid h-[28px] w-[28px] place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-sunken hover:text-text max-md:h-[44px] max-md:w-[44px]"
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
        <span className="tabular text-micro text-muted">
          {comment.length} / {MAX_COMMENT_LENGTH}
        </span>
      </div>

      <div className="flex flex-wrap gap-[var(--s-4)]">
        <Button type="submit" variant="primary" disabled={saving} className="max-md:flex-1">
          {saving ? 'Сохранение…' : 'Сохранить'}
        </Button>
        <Button type="button" onClick={onCancel} className="max-md:flex-1">
          Отмена
        </Button>
      </div>
    </form>
  );
};
