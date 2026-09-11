'use client';

import type { FC, ReactNode } from 'react';

import { UNIT_LABELS } from '@/components/workspace/TakeoffPanel';
import type {
  MeasurementQuantityRead,
  MeasurementRead,
  ScaleCalibrationRead,
  TakeoffItemRead,
} from '@quantor/api-client';

interface IMeasurementInspectorProps {
  readonly measurement: MeasurementRead | null;
  readonly item: TakeoffItemRead | null;
  readonly calibration: ScaleCalibrationRead | null;
  /** Величина, посчитанная сервером. `null` — ответ ещё не пришёл. */
  readonly quantity: MeasurementQuantityRead | null;
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

/** Показ величины. Недоступная остаётся прочерком: ноль был бы ложным утверждением. */
const QuantityValue: FC<{ quantity: MeasurementQuantityRead | null; unit: string }> = ({
  quantity,
  unit,
}) => {
  if (!quantity) return <span className="text-muted">…</span>;
  if (quantity.state !== 'ready' || quantity.value === null) {
    return (
      <span className="text-danger">
        {quantity.state === 'unavailable_no_scale' ? 'нет масштаба' : 'нет геометрии'}
      </span>
    );
  }

  // Число приходит строкой, чтобы не потерять точную десятичную запись по дороге через
  // JSON. Для показа округляем, для проверки рядом лежит каноническое значение в мм.
  return (
    <span className="tabular">
      {Number(quantity.value).toLocaleString('ru-RU', { maximumFractionDigits: 3 })} {unit}
    </span>
  );
};

/**
 * Свойства выбранного измерения.
 *
 * Величину считает сервер по правилу с версией. Клиентское число нельзя ни проверить, ни
 * воспроизвести, а величина без основания в смете не величина.
 *
 * Правило и отпечаток показаны рядом намеренно: это и есть основание, по которому величину
 * можно объяснить заказчику через полгода.
 */
export const MeasurementInspector: FC<IMeasurementInspectorProps> = ({
  measurement,
  item,
  calibration,
  quantity,
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
          <QuantityValue quantity={quantity} unit={UNIT_LABELS[item.display_unit] ?? ''} />
        </Field>
        {quantity && (
          <Field label="Правило">
            <span className="tabular text-muted">{quantity.rule_key}</span>
          </Field>
        )}
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
        {quantity && (
          <Field label="Отпечаток входа">
            {/* Полный отпечаток не помещается и не читается; хвост различает записи,
                а целиком он есть в ответе API. */}
            <span className="tabular text-muted">{quantity.input_fingerprint.slice(0, 12)}…</span>
          </Field>
        )}
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
          title="Delete или Backspace"
          className="self-start text-micro text-danger hover:underline"
        >
          Удалить измерение
        </button>
      )}
    </div>
  );
};
