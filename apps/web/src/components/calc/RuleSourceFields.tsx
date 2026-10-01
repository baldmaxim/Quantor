'use client';

import { SOURCE_FIELDS, SOURCE_KIND_TITLES, type SourceKind } from '@/lib/calc/rule-needs';

/**
 * Основание версии правила: вид и поля вида. Какие виды годятся, решает тип правила — список
 * приходит снаружи; поля «по СП» без пункта и редакции не принимаются ни здесь, ни сервером.
 */

export const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

export const TEXTAREA =
  'rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] py-[var(--s-2)] text-base text-text md:text-sm';

interface IRuleSourceFieldsProps {
  baseId: string;
  kinds: readonly SourceKind[];
  kind: SourceKind;
  values: Readonly<Record<string, string>>;
  onKind: (kind: SourceKind) => void;
  onValue: (key: string, value: string) => void;
}

export const RuleSourceFields = ({
  baseId,
  kinds,
  kind,
  values,
  onKind,
  onValue,
}: IRuleSourceFieldsProps) => (
  <fieldset className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border p-[var(--s-4)]">
    <legend className="px-[var(--s-2)] text-sm font-medium">Основание</legend>
    <label htmlFor={`${baseId}-kind`} className="flex flex-col gap-[var(--s-2)]">
      <span className="text-sm">Вид основания</span>
      <select
        id={`${baseId}-kind`}
        value={kind}
        onChange={(event) => {
          const next = kinds.find((item) => item === event.target.value);
          if (next) onKind(next);
        }}
        className={FIELD}
      >
        {kinds.map((item) => (
          <option key={item} value={item}>
            {SOURCE_KIND_TITLES[item]}
          </option>
        ))}
      </select>
    </label>
    {SOURCE_FIELDS[kind].map((field) => {
      const id = `${baseId}-${field.key}`;
      return (
        <label key={field.key} htmlFor={id} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">
            {field.title}
            {field.optional && <span className="text-muted"> — необязательно</span>}
          </span>
          {field.kind === 'long' ? (
            <textarea
              id={id}
              rows={2}
              maxLength={2000}
              value={values[field.key] ?? ''}
              onChange={(event) => onValue(field.key, event.target.value)}
              className={TEXTAREA}
            />
          ) : (
            <input
              id={id}
              type={field.kind === 'date' ? 'date' : 'text'}
              maxLength={200}
              value={values[field.key] ?? ''}
              onChange={(event) => onValue(field.key, event.target.value)}
              className={FIELD}
            />
          )}
        </label>
      );
    })}
  </fieldset>
);
