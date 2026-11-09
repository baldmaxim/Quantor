'use client';

import type { CadScaleRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Field, InspectorSection, StatusBadge } from '@/components/ui';
import {
  formatBool,
  formatInt,
  formatNumber,
  formatScaleDenominator,
  NO_VALUE,
} from '@/lib/cad/view-format';

import { CadControlsTable } from './CadControlsTable';

interface ICadScaleSectionProps {
  scale: CadScaleRead | null;
}

const LIST = 'grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-x-[var(--s-5)] gap-y-[var(--s-3)]';

/**
 * Диагностика масштаба: подбор по размерным цепочкам и независимая проверка.
 * Напечатанный масштаб (`М 1:100`) один масштаб не подтверждает - он показан отдельной строкой
 * и только как сопоставление с подобранным.
 */
export const CadScaleSection: FC<ICadScaleSectionProps> = ({ scale }) => {
  if (!scale) {
    return (
      <InspectorSection title="Масштаб">
        <p className="text-xs text-muted">Движок не записал проверку масштаба для этого вида.</p>
      </InspectorSection>
    );
  }

  const printed =
    scale.printed_scale_labels.length > 0
      ? scale.printed_scale_labels.map((label) => `1:${formatNumber(label, 1)}`).join(', ')
      : NO_VALUE;

  return (
    <InspectorSection
      title="Масштаб"
      aside={
        <StatusBadge tone={scale.passed ? 'success' : 'warning'} dot={false}>
          {scale.passed ? 'проверка пройдена' : 'не подтверждён'}
        </StatusBadge>
      }
    >
      <div className="flex min-w-0 flex-col gap-[var(--s-5)]">
        {scale.hold_reasons.length > 0 ? (
          <div
            role="alert"
            className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-5)] py-[var(--s-4)]"
          >
            <p className="text-sm font-semibold text-warning">HOLD: масштаб не подтверждён</p>
            <ul className="flex list-disc flex-col gap-[var(--s-2)] pl-[var(--s-6)] text-xs [overflow-wrap:anywhere]">
              {scale.hold_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs font-medium text-success">Подтверждён размерной проверкой</p>
        )}

        <dl className={LIST}>
          <Field label="Статус">{scale.status}</Field>
          <Field label="Метод">{scale.method ?? NO_VALUE}</Field>
          <Field label="мм на точку PDF">{formatNumber(scale.mm_per_pdf_point, 6)}</Field>
          <Field label="Масштаб">{formatScaleDenominator(scale.scale_denominator)}</Field>
          <Field label="Напечатанный масштаб">{printed}</Field>
          <Field label="Совпадает с подобранным">{formatBool(scale.printed_scale_consistent)}</Field>
          <Field label="Контролей: подбор / проверка">
            {formatInt(scale.fit_controls)} / {formatInt(scale.heldout_controls)}
          </Field>
          <Field label="Цепочек: подбор / проверка">
            {formatInt(scale.fit_chains)} / {formatInt(scale.heldout_chains)}
          </Field>
          <Field label="Цепочки подбора и проверки не пересекаются">
            {formatBool(scale.fit_and_holdout_chains_disjoint)}
          </Field>
          <Field label="Независимые оси">{formatBool(scale.independent_axes)}</Field>
          <Field label="Конфликтов привязки">{formatInt(scale.anchored_conflicts)}</Field>
          <Field label="Подписей без цепочки">{formatInt(scale.unassociated_numeric_labels)}</Field>
          <Field label="Выпуск разрешён движком">{formatBool(scale.release_allowed)}</Field>
        </dl>

        <CadControlsTable controls={scale.controls} />
      </div>
    </InspectorSection>
  );
};
