'use client';

import type { CadConstructionsRead, CadFloor3dRead } from '@quantor/api-client';
import type { FC, ReactNode } from 'react';

import { Button } from '@/components/ui';
import { KIND_LABELS } from '@/lib/cad/construction-labels';
import { formatMeters } from '@/lib/cad/floor3d-geometry';
import { heightSourceText } from '@/lib/cad/floor3d-heights';
import type { IFloor3dPick } from '@/lib/cad/floor3d-scene';
import { wallQuantities } from '@/lib/cad/floor3d-volume';
import { formatNumber } from '@/lib/cad/view-format';

const WIDTH_PX = 252;
const HEIGHT_ESTIMATE_PX = 340;
const GAP_PX = 12;
const EDGE_PX = 8;

const HOLE_STATE_TEXT = {
  candidate: 'кандидат, решения нет',
  enabled: 'отверстие',
  disabled: 'не отверстие',
} as const;

interface ICadFloor3dPopoverProps {
  readonly pick: IFloor3dPick;
  readonly model: CadFloor3dRead;
  /** Конструкции листа (тот же запрос, что у вкладки): источник длины, площади и объёма стены. */
  readonly constructions?: Pick<CadConstructionsRead, 'constructions'> | null;
  /** Точка клика от угла холста и размер холста, px. */
  readonly anchor: { readonly x: number; readonly y: number };
  readonly bounds: { readonly width: number; readonly height: number };
  readonly saving: boolean;
  readonly error: string | null;
  readonly onDecide: (key: string, enabled: boolean) => void;
  readonly onClose: () => void;
}

const Row: FC<{ readonly label: string; readonly value: string }> = ({ label, value }) => (
  <p className="text-xs [overflow-wrap:anywhere]">
    <span className="text-muted">{label}: </span>
    {value}
  </p>
);

/**
 * Карточка элемента у курсора: только просмотр (объёмов не считает), у отверстия - решение человека.
 * Кнопки по состоянию: кандидат - обе, включено - «Не отверстие», выключено - «Отверстие».
 */
export const CadFloor3dPopover: FC<ICadFloor3dPopoverProps> = ({
  pick,
  model,
  constructions = null,
  anchor,
  bounds,
  saving,
  error,
  onDecide,
  onClose,
}) => {
  let title = '';
  let body: ReactNode = null;

  if (pick.kind === 'prism' && (pick.category === 'masonry' || pick.category === 'monolith')) {
    const wall = model.walls.find((item) => item.construction_key === pick.id);
    if (!wall) return null;
    title = KIND_LABELS[wall.kind];
    const top = wall.z_top_mm;
    const quantities = wallQuantities(constructions, wall.construction_key);
    const orUndefined = (value: number | null | undefined, digits: number, unit: string): string =>
      value === null || value === undefined ? 'не определено' : formatNumber(value, digits, unit);
    body = (
      <>
        <Row label="Семейство" value={wall.family === 'monolith' ? 'монолит' : 'кладка'} />
        <Row
          label="Толщина (номинал)"
          value={wall.thickness_nominal_mm === null ? 'не определена' : `${wall.thickness_nominal_mm} мм`}
        />
        <Row label="Низ, м" value={formatMeters(wall.z_bottom_mm)} />
        <Row label="Верх, м" value={top === null ? 'не определён' : formatMeters(top)} />
        <Row label="Высота стены, м" value={top === null ? 'не определена' : formatMeters(top - wall.z_bottom_mm)} />
        <Row label="Длина по оси" value={orUndefined(quantities?.lengthM, 2, 'м')} />
        <Row label="Высота в расчёте" value={orUndefined(quantities?.heightMm, 0, 'мм')} />
        <Row label="Площадь стены" value={orUndefined(quantities?.wallAreaM2, 2, 'м²')} />
        {quantities === null || quantities.volumeM3 === null ? (
          <p className="text-xs text-muted">Объём не определён</p>
        ) : (
          <Row label="Объём" value={formatNumber(quantities.volumeM3, 3, 'м³')} />
        )}
        {quantities !== null && (
          <Row label="Состояние" value={quantities.accepted ? 'принято' : 'проверить'} />
        )}
      </>
    );
  } else if (pick.kind === 'prism' && pick.category === 'lintel') {
    const lintel = model.lintels.find((item) => item.opening_id === pick.id);
    if (!lintel) return null;
    title = lintel.kind === 'door' ? 'Перемычка над дверью' : 'Перемычка над проёмом';
    body = (
      <>
        <Row label="Высота двери" value={`${lintel.door_height_mm} мм (${heightSourceText(lintel.door_height_source)})`} />
        <Row label="Низ, м" value={formatMeters(lintel.z_bottom_mm)} />
        <Row label="Верх, м" value={formatMeters(lintel.z_top_mm)} />
      </>
    );
  } else if (pick.kind === 'hole') {
    const hole = model.slab_holes.find((item) => item.key === pick.id);
    if (!hole) return null;
    title = 'Отверстие плиты';
    body = (
      <>
        <Row label="Площадь" value={`${hole.area_m2.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} м²`} />
        <Row label="Состояние" value={HOLE_STATE_TEXT[hole.state]} />
        <div className="flex flex-wrap gap-[var(--s-3)] pt-[var(--s-2)]">
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
        </div>
      </>
    );
  } else {
    return null;
  }

  const left = Math.max(EDGE_PX, Math.min(anchor.x + GAP_PX, bounds.width - WIDTH_PX - EDGE_PX));
  const top = Math.max(EDGE_PX, Math.min(anchor.y + GAP_PX, bounds.height - HEIGHT_ESTIMATE_PX));

  return (
    <div
      role="dialog"
      aria-label={title}
      data-testid="floor3d-popover"
      // Положение у курсора - динамическое значение.
      style={{ left, top }}
      className="absolute z-10 flex max-h-[60%] w-[252px] max-w-[calc(100%-16px)] flex-col gap-[var(--s-3)] overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-4)] shadow-[var(--shadow-2)]"
    >
      <div className="flex items-start justify-between gap-[var(--s-3)]">
        <h4 className="text-sm font-semibold [overflow-wrap:anywhere]">{title}</h4>
        <button
          type="button"
          aria-label="Закрыть карточку"
          onClick={onClose}
          className="press -mt-[var(--s-2)] -mr-[var(--s-2)] grid h-[44px] w-[44px] flex-none place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text md:h-[28px] md:w-[28px]"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
      {body}
      {error !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
    </div>
  );
};
