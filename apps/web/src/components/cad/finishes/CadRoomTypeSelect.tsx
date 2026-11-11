'use client';

import type { FC } from 'react';

import {
  ROOM_TYPE_LABELS,
  roomTypesForKind,
  type RoomType,
  type RoomTypeSource,
} from '@/lib/cad/room-types';
import type { ZoneKind } from '@/lib/cad/zones';

interface ICadRoomTypeSelectProps {
  /** Вид зоны: в списке только коды этого вида (МОП или квартира). */
  kind: ZoneKind;
  value: RoomType | null;
  /** Откуда тип: «авто» - выведен сервером из названия. */
  source: RoomTypeSource | null;
  /** `null` — сбросить выбор человека: сервер снова выведет тип из названия. */
  onChange: (type: RoomType | null) => void;
  /** Доступное имя поля (aria-label). */
  label: string;
  disabled?: boolean;
}

const AUTO = '__auto__';

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

/**
 * Выбор типа помещения зоны (ADR-0042). Выведенный по названию тип помечен «авто»; выбор
 * человека сохраняется как явный. Шрифт ≥ 16 px: Safari не зумит форму при фокусе.
 */
export const CadRoomTypeSelect: FC<ICadRoomTypeSelectProps> = ({
  kind,
  value,
  source,
  onChange,
  label,
  disabled = false,
}) => {
  const types = roomTypesForKind(kind);
  if (types.length === 0) return null;
  return (
    <div className="flex min-w-0 items-center gap-[var(--s-2)]">
      <select
        aria-label={label}
        value={value ?? ''}
        disabled={disabled}
        className={FIELD}
        onChange={(event) => {
          if (event.target.value === AUTO) {
            onChange(null);
            return;
          }
          const next = types.find((type) => type === event.target.value);
          if (next !== undefined) onChange(next);
        }}
      >
        {value === null && (
          <option value="" disabled>
            Тип не задан
          </option>
        )}
        {source === 'manual' && <option value={AUTO}>Авто (по названию)</option>}
        {types.map((type) => (
          <option key={type} value={type}>
            {ROOM_TYPE_LABELS[type]}
          </option>
        ))}
      </select>
      {source === 'derived' && (
        <span
          className="shrink-0 rounded-[var(--radius-xs)] border border-border px-[var(--s-2)] text-micro text-muted"
          title="Тип выведен из названия зоны; выберите другой, чтобы исправить"
        >
          авто
        </span>
      )}
    </div>
  );
};
