'use client';

import { useMemo, useState, type FC } from 'react';

import { Button, cx } from '@/components/ui';
import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import {
  distancePdfPoints,
  normalizedToPdfDisplay,
  type PageGeometryValue,
} from '@/lib/viewer/measurement';

/** Единицы, в которых на строительных чертежах подписывают размеры. */
const UNITS = [
  { value: 'mm', label: 'мм' },
  { value: 'cm', label: 'см' },
  { value: 'm', label: 'м' },
] as const;

export type ScaleUnit = (typeof UNITS)[number]['value'];

const TO_MM: Record<ScaleUnit, number> = { mm: 1, cm: 10, m: 1000 };

interface IScaleDialogProps {
  readonly pointA: NormalizedPoint;
  readonly pointB: NormalizedPoint;
  /** Каноническая геометрия страницы. Пусто — предпросмотр показать не из чего. */
  readonly geometry: PageGeometryValue | null;
  readonly pending: boolean;
  readonly error: string | null;
  readonly onConfirm: (value: string, unit: ScaleUnit) => void;
  readonly onCancel: () => void;
}

/**
 * Ввод известного размера для калибровки масштаба.
 *
 * Предпросмотр коэффициента считается на клиенте тем же ядром, что и на сервере, — но
 * это только показ. Сохранённое значение приходит от сервера и заменяет предварительное:
 * величину, посчитанную браузером, защитить перед заказчиком нечем (ADR-0018).
 */
export const ScaleDialog: FC<IScaleDialogProps> = ({
  pointA,
  pointB,
  geometry,
  pending,
  error,
  onConfirm,
  onCancel,
}) => {
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState<ScaleUnit>('mm');

  const distancePt = useMemo(() => {
    if (!geometry) return null;
    try {
      return distancePdfPoints(
        normalizedToPdfDisplay(pointA, geometry),
        normalizedToPdfDisplay(pointB, geometry),
      );
    } catch {
      // Точка вне листа: предпросмотр не показываем, отказ придёт от сервера с кодом.
      return null;
    }
  }, [pointA, pointB, geometry]);

  const parsed = Number(value.replace(',', '.'));
  const valid = value.trim() !== '' && Number.isFinite(parsed) && parsed > 0;

  // Предпросмотр: сколько миллиметров мира приходится на точку PDF.
  const preview =
    valid && distancePt !== null && distancePt > 0 ? (parsed * TO_MM[unit]) / distancePt : null;

  const submit = () => {
    if (!valid || pending) return;
    onConfirm(value.replace(',', '.'), unit);
  };

  return (
    <div
      role="dialog"
      aria-label="Масштаб чертежа"
      className="flex w-[280px] flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-line bg-surface p-[var(--s-5)] shadow-[var(--shadow-sheet)]"
    >
      <div className="flex flex-col gap-[var(--s-1)]">
        <span className="text-body font-medium">Известный размер</span>
        <span className="text-micro text-muted">
          Введите размер, подписанный на чертеже между выбранными точками.
        </span>
      </div>

      <div className="flex gap-[var(--s-2)]">
        <input
          autoFocus
          inputMode="decimal"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit();
            if (event.key === 'Escape') onCancel();
          }}
          aria-label="Известный размер"
          placeholder="6000"
          // 16px минимум: меньше — и Safari зумит форму при фокусе.
          //
          // Фон — `surface`, а не `canvas`. `canvas` это цвет бумаги чертежа: он остаётся
          // светлым и в тёмной теме, поэтому светлый текст на нём становится невидимым.
          className="h-[var(--h-ctl)] min-w-0 flex-1 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-3)] text-body text-text tabular placeholder:text-muted"
        />
        <div className="flex rounded-[var(--radius-sm)] border border-line">
          {UNITS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setUnit(item.value)}
              aria-pressed={unit === item.value}
              className={cx(
                'h-[var(--h-ctl)] px-[var(--s-3)] text-micro',
                unit === item.value ? 'bg-accent-soft text-accent' : 'text-muted',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <dl className="flex flex-col gap-[var(--s-1)] text-micro text-muted">
        <div className="flex justify-between">
          <dt>Отрезок на листе</dt>
          <dd className="tabular">{distancePt === null ? '—' : `${distancePt.toFixed(1)} pt`}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Масштаб</dt>
          <dd className="tabular">{preview === null ? '—' : `${preview.toFixed(3)} мм/pt`}</dd>
        </div>
      </dl>

      {error && (
        <p role="alert" className="text-micro text-danger">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-[var(--s-2)]">
        <Button variant="ghost" onClick={onCancel} disabled={pending}>
          Отмена
        </Button>
        <Button variant="primary" onClick={submit} disabled={!valid || pending}>
          {pending ? 'Сохранение…' : 'Сохранить'}
        </Button>
      </div>
    </div>
  );
};
