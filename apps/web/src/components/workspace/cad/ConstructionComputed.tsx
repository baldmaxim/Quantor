'use client';

import type { CadConstructionRead } from '@quantor/api-client';
import type { FC } from 'react';

import {
  isFramePartition,
  materialLabel,
  materialSourceLabel,
  sourceLabel,
  WARNING_LABELS,
} from '@/lib/cad/construction-labels';
import { StatusBadge } from '@/components/ui';
import { formatNumber } from '@/lib/cad/view-format';

export const UNDEFINED_TEXT = 'не определено';

/** Число с единицей; отсутствие - текстом «не определено», а не нулём. */
export const numberOrUndefined = (
  value: number | null | undefined,
  digits: number,
  unit: string,
): string =>
  value === null || value === undefined ? UNDEFINED_TEXT : formatNumber(value, digits, unit);

interface IConstructionComputedProps {
  construction: CadConstructionRead;
  doors: number;
}

const ROW = 'flex min-w-0 flex-wrap justify-between gap-x-[var(--s-4)]';

/** Блок «Расчёт» карточки конструкции: только чтение, величины считает сервер. */
export const ConstructionComputed: FC<IConstructionComputedProps> = ({ construction, doors }) => {
  const { computed } = construction;
  const nominal = construction.thickness_nominal_mm;
  const { material } = construction;
  const framePartition = isFramePartition(construction.kind);
  const hintText = material.evidence[0]?.text;
  const heightSource = computed.height_mm === null ? null : sourceLabel(computed.sources.height);
  return (
    <section aria-label="Расчёт" className="flex min-w-0 flex-col gap-[var(--s-2)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Расчёт</h4>
      <dl className="m-0 flex flex-col gap-[var(--s-2)] text-xs">
        <div className={ROW}>
          <dt className="text-muted">Материал</dt>
          <dd className="m-0 flex min-w-0 flex-wrap items-center gap-x-[var(--s-3)]">
            {materialLabel(material.value)}
            {material.value !== null && material.source === 'document' && (
              <span title={hintText}>
                <StatusBadge tone="accent" dot={false}>
                  из документа
                </StatusBadge>
              </span>
            )}
            {material.value !== null && material.source === 'manual' && (
              <span className="text-muted">({materialSourceLabel(material.source)})</span>
            )}
            {computed.warnings.includes('material_check') && (
              <StatusBadge tone="warning" dot={false}>
                проверить материал
              </StatusBadge>
            )}
          </dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Толщина измеренная / номинал</dt>
          <dd className="m-0">
            {numberOrUndefined(construction.thickness_measured_mm, 1, 'мм')} /{' '}
            {nominal === null ? UNDEFINED_TEXT : `${nominal} мм`}
          </dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Длина</dt>
          <dd className="m-0">{numberOrUndefined(computed.length_m, 2, 'м')}</dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Высота</dt>
          <dd className="m-0">
            {numberOrUndefined(computed.height_mm, 0, 'мм')}
            {heightSource !== null && <span className="text-muted"> ({heightSource})</span>}
          </dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Площадь стены</dt>
          <dd className="m-0">{numberOrUndefined(computed.wall_area_m2, 2, 'м²')}</dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Объём</dt>
          <dd className="m-0">
            {framePartition ? '—' : numberOrUndefined(computed.volume_m3, 3, 'м³')}
          </dd>
        </div>
        <div className={ROW}>
          <dt className="text-muted">Двери в стене</dt>
          <dd className="m-0">{doors}</dd>
        </div>
      </dl>
      {computed.warnings.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0 text-xs text-warning">
          {computed.warnings.map((warning) => (
            <li key={warning}>{WARNING_LABELS[warning]}</li>
          ))}
        </ul>
      )}
    </section>
  );
};
