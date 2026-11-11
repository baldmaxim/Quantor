'use client';

import type { CadScaleRead } from '@quantor/api-client';
import type { FC } from 'react';

import { InspectorSection, StatusBadge } from '@/components/ui';
import {
  formatDeviationPercent,
  formatScaleDenominator,
  formatScaleFromMmPerPt,
  NO_VALUE,
} from '@/lib/cad/view-format';

import { CadControlsTable } from './CadControlsTable';

interface ICadScaleSectionProps {
  scale: CadScaleRead | null;
}

/** «1:N»: при калибровке человека - из неё, иначе - масштаб, подобранный движком. */
const scaleText = (scale: CadScaleRead): string => {
  const fromCalibration = formatScaleFromMmPerPt(scale.operator_mm_per_pt ?? scale.mm_per_pdf_point);
  const fromEngine = formatScaleDenominator(scale.scale_denominator);
  const text = scale.source ? fromCalibration : fromEngine;
  if (text !== NO_VALUE) return text;
  return fromCalibration !== NO_VALUE ? fromCalibration : fromEngine;
};

/** Причины, по которым масштаб не подтверждён: причины отказа, иначе общая причина. */
const reasonsOf = (scale: CadScaleRead): readonly string[] => {
  if (scale.hold_reasons.length > 0) return scale.hold_reasons;
  return scale.reason ? [scale.reason] : [];
};

/** Раздел «Масштаб» словами: сам масштаб, подтверждён ли он и отклонение от размерных цепочек. */
export const CadScaleSection: FC<ICadScaleSectionProps> = ({ scale }) => {
  if (!scale) {
    return (
      <InspectorSection title="Масштаб">
        <p className="text-xs text-muted">Движок не записал проверку масштаба для этого вида.</p>
      </InspectorSection>
    );
  }

  const confirmed = scale.passed && scale.hold_reasons.length === 0;
  const reasons = confirmed ? [] : reasonsOf(scale);
  const hasDeviation = scale.deviation !== null && scale.deviation !== undefined;

  return (
    <InspectorSection
      title="Масштаб"
      aside={
        <StatusBadge tone={confirmed ? 'success' : 'warning'} dot={false}>
          {confirmed ? 'подтверждён' : 'не подтверждён'}
        </StatusBadge>
      }
    >
      <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="cad-scale-summary">
        <p className="text-sm font-medium">Масштаб {scaleText(scale)}</p>
        {hasDeviation && (
          <p className="text-sm">
            Отклонение от размерных цепочек: {formatDeviationPercent(scale.deviation)}
          </p>
        )}
        <CadControlsTable controls={scale.controls} />
        {reasons.length > 0 && (
          <div
            role="alert"
            className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-5)] py-[var(--s-4)]"
          >
            <p className="text-sm font-semibold text-warning">Масштаб не подтверждён</p>
            <ul className="flex list-disc flex-col gap-[var(--s-2)] pl-[var(--s-6)] text-xs [overflow-wrap:anywhere]">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </InspectorSection>
  );
};
