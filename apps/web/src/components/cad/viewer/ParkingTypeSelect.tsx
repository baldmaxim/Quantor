'use client';

import type { FC } from 'react';

import { PARKING_TYPES, PARKING_TYPE_LABELS, type ParkingType } from '@/lib/cad/zones';

interface IParkingTypeSelectProps {
  value: ParkingType;
  onChange: (type: ParkingType) => void;
  /** Доступное имя поля (aria-label). */
  label: string;
  disabled?: boolean;
}

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

/** Выбор типа машино-места по легенде листа: 10 типов; шрифт ≥ 16 px (Safari не зумит форму). */
export const ParkingTypeSelect: FC<IParkingTypeSelectProps> = ({
  value,
  onChange,
  label,
  disabled = false,
}) => (
  <select
    aria-label={label}
    value={value}
    disabled={disabled}
    className={FIELD}
    onChange={(event) => {
      const next = PARKING_TYPES.find((type) => type === event.target.value);
      if (next !== undefined) onChange(next);
    }}
  >
    {PARKING_TYPES.map((type) => (
      <option key={type} value={type}>
        {PARKING_TYPE_LABELS[type]}
      </option>
    ))}
  </select>
);
