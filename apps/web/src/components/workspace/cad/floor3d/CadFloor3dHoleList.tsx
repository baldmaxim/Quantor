'use client';

import type { CadFloor3dRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button } from '@/components/ui';

type SlabHole = CadFloor3dRead['slab_holes'][number];

const STATE_TEXT: Record<SlabHole['state'], string> = {
  candidate: 'кандидат',
  enabled: 'отверстие',
  disabled: 'не отверстие',
};

interface ICadFloor3dHoleListProps {
  readonly holes: readonly SlabHole[];
  readonly saving: boolean;
  readonly onDecide: (key: string, enabled: boolean) => void;
}

const count = (holes: readonly SlabHole[], state: SlabHole['state']): number =>
  holes.filter((hole) => hole.state === state).length;

/**
 * Список отверстий плиты (ADR-0039): площадь, состояние и переключатель решения человека. Нужен,
 * чтобы вернуть отверстие, помеченное «Не отверстие»: на сцене оно лишь тонкий контур. Строка
 * ничего не выделяет на сцене. Сортировка - по убыванию площади.
 */
export const CadFloor3dHoleList: FC<ICadFloor3dHoleListProps> = ({ holes, saving, onDecide }) => {
  const [open, setOpen] = useState(false);
  const sorted = useMemo(() => [...holes].sort((a, b) => b.area_m2 - a.area_m2), [holes]);
  if (holes.length === 0) return null;

  return (
    <section aria-label="Отверстия плиты" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="press flex min-h-[44px] w-full items-center justify-between gap-[var(--s-3)] text-left"
      >
        <span className="min-w-0">
          <span className="block text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            Отверстия плиты ({holes.length})
          </span>
          <span className="block text-xs text-muted">
            кандидатов {count(holes, 'candidate')}, отверстий {count(holes, 'enabled')}, не отверстий{' '}
            {count(holes, 'disabled')}
          </span>
        </span>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <ul className="flex flex-col gap-[var(--s-2)]">
          {sorted.map((hole) => (
            <li
              key={hole.key}
              data-testid={`floor3d-hole-${hole.key}`}
              className="flex flex-wrap items-center justify-between gap-[var(--s-3)] text-xs"
            >
              <span className="min-w-0 [overflow-wrap:anywhere]">
                {hole.area_m2.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} м²
                <span className="text-muted"> · {STATE_TEXT[hole.state]}</span>
              </span>
              <span className="flex flex-wrap gap-[var(--s-2)]">
                {hole.state !== 'enabled' && (
                  <Button disabled={saving} className="max-md:h-[44px]" onClick={() => onDecide(hole.key, true)}>
                    Отверстие
                  </Button>
                )}
                {hole.state !== 'disabled' && (
                  <Button disabled={saving} className="max-md:h-[44px]" onClick={() => onDecide(hole.key, false)}>
                    Не отверстие
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};
