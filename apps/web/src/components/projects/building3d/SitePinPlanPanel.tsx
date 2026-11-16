'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { cx } from '@quantor/ui';
import { useMemo, useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { floorKey } from '@/lib/cad/building3d-geometry';
import { sitePinFloorLabel } from '@/lib/cad/site-pin-floors';
import {
  buildSitePlan,
  EMPTY_PIN_POINTS,
  nextSlot,
  withPoint,
  type MmPoint,
  type PinPoints,
  type PinSlot,
} from '@/lib/cad/site-pin-geometry';

import { SitePinPlanCanvas } from './SitePinPlanCanvas';

interface ISitePinPlanPanelProps {
  /** «Корпус» или «Площадка»: заголовок и имя области для программ чтения. */
  readonly title: string;
  readonly floors: readonly CadBuilding3dFloorRead[];
  readonly floorValue: string;
  readonly onFloorChange: (key: string) => void;
  readonly points: PinPoints;
  readonly onPointsChange: (points: PinPoints) => void;
}

const SELECT =
  'h-[44px] min-w-0 flex-1 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:h-8 md:text-sm';
const SLOT_BUTTON =
  'inline-flex min-h-[44px] items-center gap-[var(--s-2)] rounded-[var(--radius-sm)] border px-[var(--s-3)] text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent md:min-h-8';

/** Цвет номера точки совпадает с цветом маркера на холсте: 1 - чернила листа, 2 - чернила листа «опасность». */
const SLOT_DOT = ['bg-[var(--sheet-ink)]', 'bg-[var(--sheet-ink-danger)]'] as const;

/**
 * Одна панель диалога привязки: выбор этажа, план сверху и легенда точек 1 и 2. Щелчок ставит первую
 * пустую точку; щелчок по номеру в легенде назначает точку, которую следующий щелчок поставит заново.
 * Диалог ставит `key` по этажу: со сменой этажа назначенная точка и вид сбрасываются.
 */
export const SitePinPlanPanel: FC<ISitePinPlanPanelProps> = ({
  title,
  floors,
  floorValue,
  onFloorChange,
  points,
  onPointsChange,
}) => {
  const [armed, setArmed] = useState<PinSlot | null>(null);
  const [fitSeq, setFitSeq] = useState(0);
  const floor = useMemo(() => floors.find((item) => floorKey(item) === floorValue) ?? null, [floors, floorValue]);
  const plan = useMemo(() => (floor === null ? null : buildSitePlan(floor)), [floor]);
  const selectId = `site-pin-floor-${title}`;

  const pick = (point: MmPoint): void => {
    const slot = nextSlot(points, armed);
    if (slot === null) return;
    onPointsChange(withPoint(points, slot, point));
    setArmed(null);
  };

  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <div className="flex items-center gap-[var(--s-3)]">
        <label htmlFor={selectId} className="flex-none text-sm font-medium">
          {title}
        </label>
        <select
          id={selectId}
          value={floorValue}
          onChange={(event) => onFloorChange(event.target.value)}
          className={SELECT}
        >
          {floors.map((item) => (
            <option key={floorKey(item)} value={floorKey(item)}>
              {sitePinFloorLabel(item)}
            </option>
          ))}
        </select>
        <Button className="min-h-[44px] flex-none md:min-h-8" onClick={() => setFitSeq((value) => value + 1)}>
          Вписать
        </Button>
      </div>
      {plan === null ? (
        <p role="status" className="text-sm text-muted">
          У этажа нет контуров для привязки.
        </p>
      ) : (
        <SitePinPlanCanvas
          plan={plan}
          points={points}
          armed={armed}
          fitSeq={fitSeq}
          label={`План: ${title}. Щелчок ставит точку, колесо - масштаб, перетаскивание - сдвиг`}
          onPick={pick}
        />
      )}
      <div className="flex flex-wrap items-center gap-[var(--s-2)]">
        {([0, 1] as const).map((slot) => (
          <button
            key={slot}
            type="button"
            aria-pressed={armed === slot}
            aria-label={`${title}: точка ${slot + 1}${points[slot] === null ? ', не поставлена' : ', поставлена'}`}
            onClick={() => setArmed((value) => (value === slot ? null : slot))}
            className={cx(
              SLOT_BUTTON,
              armed === slot ? 'border-accent bg-bg text-accent' : 'border-border-control text-text',
            )}
          >
            <span aria-hidden="true" className={cx('inline-block size-3 rounded-full', SLOT_DOT[slot])} />
            Точка {slot + 1}
            <span className="text-xs text-muted">{points[slot] === null ? 'нет' : 'есть'}</span>
          </button>
        ))}
        <Button
          className="min-h-[44px] md:min-h-8"
          disabled={points[0] === null && points[1] === null}
          onClick={() => {
            onPointsChange(EMPTY_PIN_POINTS);
            setArmed(null);
          }}
        >
          Сбросить
        </Button>
      </div>
    </section>
  );
};
