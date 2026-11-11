'use client';

import type { RiserRole, RiserSystem } from '@quantor/api-client';
import { useId, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  RISER_ROLES,
  RISER_ROLE_LABELS,
  RISER_SYSTEMS,
  RISER_SYSTEM_LABELS,
  type IRiserDraft,
  type IRiserProblems,
} from '@/lib/cad/risers';

interface ICadRiserRowProps {
  readonly index: number;
  readonly draft: IRiserDraft;
  /** Ошибки показываются после первой попытки сохранить. */
  readonly problems: IRiserProblems | null;
  readonly disabled: boolean;
  readonly onChange: (patch: Partial<IRiserDraft>) => void;
  readonly onRemove: () => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const SELECT =
  'h-[var(--h-ctl)] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

const Problem: FC<{ text: string | undefined }> = ({ text }) =>
  text ? (
    <span role="alert" className="text-xs text-danger">
      {text}
    </span>
  ) : null;

/**
 * Одна запись реестра: карточка из двух колонок, на узкой панели и на телефоне без
 * горизонтального скролла. Система и роль - списки, остальное - поля с крестиком.
 */
export const CadRiserRow: FC<ICadRiserRowProps> = ({
  index,
  draft,
  problems,
  disabled,
  onChange,
  onRemove,
}) => {
  const id = useId();
  const title = `Стояк ${index + 1}`;
  return (
    <li
      aria-label={title}
      data-testid="cad-riser-row"
      className="grid min-w-0 grid-cols-2 gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border bg-surface p-[var(--s-4)]"
    >
      <label className={`${LABEL} col-span-2`} htmlFor={`${id}-system`}>
        Система
        <select
          id={`${id}-system`}
          value={draft.system}
          disabled={disabled}
          className={SELECT}
          onChange={(event) => onChange({ system: event.target.value as RiserSystem })}
        >
          {RISER_SYSTEMS.map((system) => (
            <option key={system} value={system}>
              {RISER_SYSTEM_LABELS[system]}
            </option>
          ))}
        </select>
      </label>

      <label className={`${LABEL} col-span-2`}>
        Марка
        <ClearableInput
          label={`Марка, ${title}`}
          value={draft.mark}
          maxLength={64}
          autoComplete="off"
          placeholder="например, В1.1.1"
          disabled={disabled}
          wrapperClassName="w-full"
          aria-invalid={problems?.mark !== undefined}
          onChange={(event) => onChange({ mark: event.target.value })}
          onClear={() => onChange({ mark: '' })}
        />
        <Problem text={problems?.mark} />
      </label>

      <label className={LABEL}>
        Ø, мм
        <ClearableInput
          label={`Диаметр, мм, ${title}`}
          value={draft.dn}
          inputMode="numeric"
          maxLength={3}
          autoComplete="off"
          disabled={disabled}
          wrapperClassName="w-full"
          aria-invalid={problems?.dn !== undefined}
          onChange={(event) => onChange({ dn: event.target.value })}
          onClear={() => onChange({ dn: '' })}
        />
        <Problem text={problems?.dn} />
      </label>

      <label className={LABEL}>
        Количество
        <ClearableInput
          label={`Количество, ${title}`}
          value={draft.count}
          inputMode="numeric"
          maxLength={1}
          autoComplete="off"
          disabled={disabled}
          wrapperClassName="w-full"
          aria-invalid={problems?.count !== undefined}
          onChange={(event) => onChange({ count: event.target.value })}
          onClear={() => onChange({ count: '' })}
        />
        <Problem text={problems?.count} />
      </label>

      <label className={LABEL} htmlFor={`${id}-role`}>
        Стояк
        <select
          id={`${id}-role`}
          value={draft.role}
          disabled={disabled}
          className={SELECT}
          onChange={(event) => onChange({ role: event.target.value as RiserRole })}
        >
          {RISER_ROLES.map((role) => (
            <option key={role} value={role}>
              {RISER_ROLE_LABELS[role]}
            </option>
          ))}
        </select>
      </label>

      <label className={LABEL}>
        Шахта (необязательно)
        <ClearableInput
          label={`Шахта, ${title}`}
          value={draft.shaftId}
          maxLength={4}
          autoComplete="off"
          placeholder="S12"
          disabled={disabled}
          wrapperClassName="w-full"
          aria-invalid={problems?.shaftId !== undefined}
          onChange={(event) => onChange({ shaftId: event.target.value })}
          onClear={() => onChange({ shaftId: '' })}
        />
        <Problem text={problems?.shaftId} />
      </label>

      <label className={`${LABEL} col-span-2`}>
        Источник
        <ClearableInput
          label={`Источник, ${title}`}
          value={draft.source}
          maxLength={200}
          autoComplete="off"
          placeholder="например, ИОС2.1 л.2"
          disabled={disabled}
          wrapperClassName="w-full"
          aria-invalid={problems?.source !== undefined}
          onChange={(event) => onChange({ source: event.target.value })}
          onClear={() => onChange({ source: '' })}
        />
        <Problem text={problems?.source} />
      </label>

      <Button
        compact
        disabled={disabled}
        aria-label={`Удалить: ${title}`}
        className="col-span-2 self-start max-md:h-[44px] max-md:w-full"
        onClick={onRemove}
      >
        Удалить строку
      </Button>
    </li>
  );
};
