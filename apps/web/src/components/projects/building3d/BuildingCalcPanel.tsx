'use client';

import { useId, useState, type FC } from 'react';

import { cx } from '@/components/ui';
import { systemColorToken } from '@/lib/tender/systems';

import type { IBuildingCalc } from './useBuildingCalc';

/**
 * Переключатель расчётов TENDER в панели просмотрщика объекта (ADR-0051): список расчётов с геометрией на
 * этажах здания, галочка - показать на этажах. Виды грузятся по включению.
 */
export const BuildingCalcPanel: FC<Pick<IBuildingCalc, 'rows' | 'onToggle'>> = ({ rows, onToggle }) => {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const shown = rows.filter((row) => row.selected).length;

  return (
    <div
      data-testid="building-calc"
      className="absolute top-[var(--s-3)] right-[var(--s-3)] z-10 flex max-h-[60%] w-[min(320px,calc(100%-24px))] flex-col overflow-hidden rounded-[var(--radius-sm)] border border-border bg-surface/95 text-sm"
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[44px] items-center justify-between gap-[var(--s-3)] px-[var(--s-3)] text-left font-medium md:min-h-8"
      >
        <span>Расчёты</span>
        <span className="tabular text-xs font-normal text-muted">
          {shown} / {rows.length}
        </span>
      </button>
      <div
        id={bodyId}
        hidden={!open}
        className="flex min-h-0 flex-col overflow-y-auto border-t border-border px-[var(--s-3)] [overscroll-behavior:contain]"
      >
        {rows.map((row) => (
          <label key={row.layer.calc_id} className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
            <input
              type="checkbox"
              checked={row.selected}
              onChange={(event) => onToggle(row.layer.calc_id, event.target.checked)}
              className="size-5 shrink-0"
            />
            <span
              aria-hidden="true"
              // Цвет системы - динамическое значение: токен темы.
              style={{ backgroundColor: `var(${systemColorToken(row.layer.system)})` }}
              className={cx(
                'size-4 shrink-0 rounded-[var(--radius-xs)] border border-border-strong',
                !row.selected && 'opacity-30',
              )}
            />
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
              {row.layer.title} · №{row.layer.number} {row.layer.label}
            </span>
            <span className="tabular flex-none text-xs text-muted">
              {row.selected ? `${row.loaded} / ${row.floors}` : `${row.floors} эт.`}
              {row.failed > 0 ? ` · ошибок ${row.failed}` : ''}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
};
