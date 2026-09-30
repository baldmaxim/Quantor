'use client';

import type {
  CalcFactTypeRead,
  CalcReadinessRowRead,
  CalcReadinessValueRead,
} from '@quantor/api-client';

import { Button, StatusBadge, cx } from '@/components/ui';
import {
  LEVEL_SHORT,
  READINESS_STATUS,
  SOURCE_CLASS_TITLES,
  formatSubject,
  formatValue,
  unitTitle,
} from '@/lib/calc/format';

/**
 * Требования одной системы: что нужно расчёту, найдено ли и откуда.
 *
 * «Не найдено» и «не проверено» — разные строки и разные слова: первое значит, что все
 * распознанные документы просмотрены, второе — что система ещё не смотрела документ. Число
 * у отсутствующего значения не показывается никогда: вместо него прочерк и причина.
 */

const COLUMNS = 'minmax(220px,1.6fr) 140px minmax(200px,1.6fr) minmax(200px,1.4fr)';
const SHOWN_VALUES = 3;

/** Где ручной ввод уместен: значения нет или оно не определено. Расхождение решают, а не дописывают. */
const ENTERABLE: ReadonlySet<CalcReadinessRowRead['status']> = new Set([
  'MISSING',
  'UNKNOWN',
  'MANUAL_REQUIRED',
  'NOT_INSPECTED',
]);

/**
 * Поэтажное данное «найдено», даже если этажей не хватает: полноту по этажам проверяет расчёт.
 * Недостающий этаж (в том числе явный 0 на нежилом) вносится вручную, не трогая найденные.
 */
const addsFloor = (row: CalcReadinessRowRead, type: CalcFactTypeRead): boolean =>
  row.status === 'FOUND' && type.required_subject.includes('floor');

interface IReadinessActions {
  /** Ввести значение вручную — последний путь; нет права — кнопки нет. */
  onEnter?: (row: CalcReadinessRowRead) => void;
  /** Расхождение источников: варианты видят все, решает проверяющий. */
  onResolve?: (conflictId: string) => void;
}

interface IReadinessTableProps extends IReadinessActions {
  rows: readonly CalcReadinessRowRead[];
  factTypes: ReadonlyMap<string, CalcFactTypeRead>;
}

export const ReadinessTable = ({ rows, factTypes, onEnter, onResolve }: IReadinessTableProps) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="hidden items-center gap-[var(--s-6)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase md:grid"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Исходное данное</span>
      <span>Статус</span>
      <span>Значение</span>
      <span>Источник или причина</span>
    </div>
    <ul className="list-none">
      {rows.map((row) => (
        <ReadinessRow
          key={row.requirement_id}
          row={row}
          type={factTypes.get(row.fact_type)}
          onEnter={onEnter}
          onResolve={onResolve}
        />
      ))}
    </ul>
  </div>
);

const valueText = (item: CalcReadinessValueRead, type: CalcFactTypeRead | undefined): string => {
  const qualifier = type?.qualifier_options.find(
    (option) => option.value === item.subject.qualifier,
  )?.title;
  const unit = type?.unit_title ?? unitTitle(type?.unit);
  const value = formatValue(item.value, type);
  return `${formatSubject(item.subject, qualifier)}: ${value}${unit ? ` ${unit}` : ''}`;
};

const ReadinessRow = ({
  row,
  type,
  onEnter,
  onResolve,
}: IReadinessActions & {
  row: CalcReadinessRowRead;
  type: CalcFactTypeRead | undefined;
}) => {
  const status = READINESS_STATUS[row.status];
  const shown = row.values.slice(0, SHOWN_VALUES);
  const more = row.values.length - shown.length;
  const sources = [
    ...new Set(
      row.values
        .map(
          (item) =>
            item.source_title ??
            (item.source_class ? SOURCE_CLASS_TITLES[item.source_class] : null),
        )
        .filter((title): title is string => title !== null),
    ),
  ];

  return (
    <li
      className={cx(
        'flex flex-wrap items-start gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0',
        'md:grid md:gap-x-[var(--s-6)] md:px-[var(--s-6)] md:py-[var(--s-3)]',
      )}
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span className="flex min-w-0 basis-full flex-col md:basis-auto">
        <span className="text-sm font-medium wrap-anywhere">{row.title}</span>
        <span className="text-xs text-muted">{LEVEL_SHORT[row.level]}</span>
      </span>

      <span className="flex flex-col items-start gap-[var(--s-2)]">
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        {onEnter && type && (ENTERABLE.has(row.status) || addsFloor(row, type)) && (
          <Button compact onClick={() => onEnter(row)}>
            {ENTERABLE.has(row.status) ? 'Ввести значение' : 'Добавить этаж'}
          </Button>
        )}
      </span>

      <span className="flex min-w-0 basis-full flex-col text-sm md:basis-auto">
        {shown.length === 0 ? (
          <span className="text-muted">—</span>
        ) : (
          shown.map((item) => (
            <span key={item.fact_key} className="flex flex-wrap items-center gap-x-[var(--s-3)]">
              <span className="tabular wrap-anywhere">{valueText(item, type)}</span>
              {onResolve && item.conflict_id && (
                <Button compact onClick={() => onResolve(item.conflict_id ?? '')}>
                  Варианты
                </Button>
              )}
            </span>
          ))
        )}
        {more > 0 && <span className="text-xs text-muted">и ещё {more}</span>}
      </span>

      <span className="flex min-w-0 basis-full flex-col text-xs text-muted md:basis-auto">
        {sources.length > 0 && <span className="wrap-anywhere">{sources.join('; ')}</span>}
        {row.reason && <span className="wrap-anywhere">{row.reason}</span>}
        {row.excluded_count > 0 && (
          <span className="text-warning">
            В ВОР Заказчика: {row.excluded_count} — только сверка
          </span>
        )}
      </span>
    </li>
  );
};
