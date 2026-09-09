'use client';

import type { FC, ReactNode } from 'react';

import { UNIT_LABELS } from '@/components/workspace/TakeoffPanel';
import type { MeasurementRead, ScaleCalibrationRead, TakeoffItemRead } from '@quantor/api-client';

interface IMeasurementInspectorProps {
  readonly measurement: MeasurementRead | null;
  readonly item: TakeoffItemRead | null;
  readonly calibration: ScaleCalibrationRead | null;
  readonly sheetLabel: string | null;
  readonly canEdit: boolean;
  readonly onDelete: (measurementId: string) => void;
}

const Field: FC<{ label: string; children: ReactNode }> = ({ label, children }) => (
  <div className="flex items-baseline justify-between gap-[var(--s-3)] py-[var(--s-1)]">
    <dt className="text-micro text-muted">{label}</dt>
    <dd className="min-w-0 truncate text-right text-micro">{children}</dd>
  </div>
);

const TYPE_LABELS: Record<string, string> = {
  count: 'Количество',
  line: 'Линия',
  polyline: 'Ломаная',
  polygon: 'Площадь',
};

/**
 * Свойства выбранного измерения.
 *
 * Величина показывается только та, что посчитал сервер. Правило подсчёта с версией
 * появляется в промте 12, поэтому пока здесь честный прочерк, а не выдуманное число:
 * «примерно столько» в смете хуже, чем «пока неизвестно».
 */
export const MeasurementInspector: FC<IMeasurementInspectorProps> = ({
  measurement,
  item,
  calibration,
  sheetLabel,
  canEdit,
  onDelete,
}) => {
  if (!measurement || !item) {
    return (
      <p className="p-[var(--s-4)] text-micro text-muted">
        Выберите измерение на чертеже, чтобы увидеть его свойства.
      </p>
    );
  }

  const scaled = measurement.scale_calibration_id !== null;
  const needsScale = item.geometry_type !== 'count';

  return (
    <div className="flex flex-col gap-[var(--s-4)] p-[var(--s-4)]">
      <dl className="flex flex-col">
        <Field label="Строка">{item.name}</Field>
        <Field label="Тип">{TYPE_LABELS[item.geometry_type] ?? item.geometry_type}</Field>
        <Field label="Источник">
          {measurement.source === 'manual' ? 'Вручную' : measurement.source}
        </Field>
        <Field label="Величина">
          {/* Величину считает сервер по правилу с версией. До промта 12 её нет. */}
          <span className="tabular">— {UNIT_LABELS[item.display_unit] ?? ''}</span>
        </Field>
        <Field label="Масштаб">
          {scaled && calibration ? (
            <span className="tabular">{Number(calibration.mm_per_pt).toFixed(3)} мм/pt</span>
          ) : needsScale ? (
            <span className="text-danger">не задан</span>
          ) : (
            // Счёту масштаб не нужен: штуки не зависят от размера страницы.
            <span className="text-muted">не требуется</span>
          )}
        </Field>
        <Field label="Лист">{sheetLabel ?? '—'}</Field>
        <Field label="Версия">
          <span className="tabular">{measurement.version}</span>
        </Field>
        <Field label="Вершин">
          <span className="tabular">{measurement.points.length}</span>
        </Field>
      </dl>

      {!scaled && needsScale && (
        <p role="status" className="text-micro text-danger">
          Масштаб не задан — длину и площадь считать не от чего. Задайте его инструментом «Масштаб».
        </p>
      )}

      {canEdit && (
        <button
          type="button"
          onClick={() => onDelete(measurement.id)}
          className="self-start text-micro text-danger hover:underline"
        >
          Удалить измерение
        </button>
      )}
    </div>
  );
};
