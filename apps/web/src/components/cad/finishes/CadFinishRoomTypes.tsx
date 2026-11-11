'use client';

import type { FC } from 'react';

import type { CadFinishTemplateRead } from '@quantor/api-client';

import { ROOM_TYPE_GROUPS, ROOM_TYPE_LABELS, type RoomType } from '@/lib/cad/room-types';

interface ICadFinishRoomTypesProps {
  selected: readonly RoomType[];
  onChange: (types: readonly RoomType[]) => void;
  /** Шаблоны проекта: тип, занятый другим шаблоном, недоступен. */
  templates: readonly CadFinishTemplateRead[];
  /** Редактируемый шаблон: его собственные типы не считаются занятыми; `null` - новый. */
  editingId: string | null;
  disabled?: boolean;
}

/** Шаблон проекта, у которого уже есть этот тип (кроме редактируемого). */
const ownerOf = (
  templates: readonly CadFinishTemplateRead[],
  editingId: string | null,
  type: RoomType,
): CadFinishTemplateRead | null =>
  templates.find((item) => item.id !== editingId && item.room_types.includes(type)) ?? null;

/**
 * Типы помещений для автоназначения шаблона: чекбоксы по группам «МОП» и «Квартира». Тип другого
 * шаблона неактивен с подписью его названия: один тип - один шаблон проекта.
 */
export const CadFinishRoomTypes: FC<ICadFinishRoomTypesProps> = ({
  selected,
  onChange,
  templates,
  editingId,
  disabled = false,
}) => (
  <fieldset className="m-0 flex min-w-0 flex-col gap-[var(--s-3)] border-0 p-0" disabled={disabled}>
    <legend className="mb-[var(--s-2)] p-0 text-xs font-semibold">
      Типы помещений для автоназначения
    </legend>
    {ROOM_TYPE_GROUPS.map((group) => (
      <div
        key={group.id}
        role="group"
        aria-label={group.title}
        className="flex min-w-0 flex-col gap-[var(--s-1)]"
      >
        <span className="text-micro tracking-[0.06em] text-muted uppercase">{group.title}</span>
        {group.types.map((type) => {
          const owner = ownerOf(templates, editingId, type);
          const checked = selected.includes(type);
          return (
            <label
              key={type}
              className="flex min-h-[44px] min-w-0 cursor-pointer items-center gap-[var(--s-3)] text-sm"
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={owner !== null}
                onChange={() =>
                  onChange(checked ? selected.filter((item) => item !== type) : [...selected, type])
                }
                className="h-[18px] w-[18px] shrink-0 accent-[var(--accent)]"
              />
              <span className={owner !== null ? 'min-w-0 text-muted' : 'min-w-0'}>
                {ROOM_TYPE_LABELS[type]}
                {owner !== null && <span className="text-xs"> — в шаблоне «{owner.name}»</span>}
              </span>
            </label>
          );
        })}
      </div>
    ))}
  </fieldset>
);
