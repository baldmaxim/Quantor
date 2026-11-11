'use client';

import type { CadBuilding3dGroupRead } from '@quantor/api-client';
import type { FC } from 'react';

export interface ICadBuilding3dGroupSelectProps {
  readonly groups: readonly CadBuilding3dGroupRead[];
  readonly value: string;
  readonly onChange: (key: string) => void;
}

const SELECT =
  'h-[44px] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text lg:text-sm';

/** Переключатель здания (корпус + секция) колонки «Здание». Скрыт, когда здание одно. */
export const CadBuilding3dGroupSelect: FC<ICadBuilding3dGroupSelectProps> = ({ groups, value, onChange }) => {
  if (groups.length <= 1) return null;
  return (
    <label className="flex flex-none flex-col gap-[var(--s-2)] px-[var(--s-4)] pb-[var(--s-2)] text-xs text-muted">
      Корпус и секция
      <select value={value} onChange={(event) => onChange(event.target.value)} className={SELECT}>
        {groups.map((group) => (
          <option key={group.key} value={group.key}>
            {`${group.label} · ${group.floor_count} эт.`}
          </option>
        ))}
      </select>
    </label>
  );
};
