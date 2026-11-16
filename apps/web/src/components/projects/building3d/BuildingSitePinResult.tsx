'use client';

import type { CadSitePinRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { formatMm } from '@/lib/cad/floor3d-measure';

interface IBuildingSitePinResultProps {
  readonly pin: CadSitePinRead;
  readonly onDismiss: () => void;
}

const degrees = (value: number): string => `${Number(value.toFixed(2)).toLocaleString('ru-RU')}°`;

/** Итог принятой привязки: поворот, сдвиг и невязка - ровно то, что вернул сервер. */
export const BuildingSitePinResult: FC<IBuildingSitePinResultProps> = ({ pin, onDismiss }) => (
  <div
    role="status"
    className="flex items-start justify-between gap-[var(--s-3)] px-[var(--s-4)] py-[var(--s-3)] text-sm"
  >
    <p className="min-w-0 [overflow-wrap:anywhere]">
      Привязка принята: поворот {degrees(pin.rotation_deg)}, сдвиг {formatMm(pin.offset_x_mm, true)} /{' '}
      {formatMm(pin.offset_y_mm, true)} мм, невязка {formatMm(pin.residual_mm)} мм (база {formatMm(pin.baseline_mm)} мм).
    </p>
    <Button className="min-h-[44px] flex-none md:min-h-8" onClick={onDismiss}>
      Скрыть
    </Button>
  </div>
);
