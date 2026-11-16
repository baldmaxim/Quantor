'use client';

import type { CadScaleRead } from '@quantor/api-client';
import type { FC } from 'react';

import { InspectorSection, StatusBadge } from '@/components/ui';
import { formatCadScale, formatDeviationPercent } from '@/lib/cad/view-format';

import { CadControlsTable } from './CadControlsTable';

interface ICadScaleSectionProps {
  scale: CadScaleRead | null;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

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
        <p className="text-sm font-medium">Масштаб {formatCadScale(scale)}</p>
        {hasDeviation && (
          <p className="text-sm">
            Отклонение от размерных цепочек: {formatDeviationPercent(scale.deviation)}
          </p>
        )}
        {scale.controls.length === 0 ? (
          <CadControlsTable controls={scale.controls} />
        ) : (
          // Таблица контролей нужна при разборе отказа: у подтверждённого масштаба она свёрнута.
          <details open={!confirmed} className="flex min-w-0 flex-col gap-[var(--s-2)]">
            <summary className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}>
              Контрольные цепочки ({scale.controls.length})
            </summary>
            <CadControlsTable controls={scale.controls} />
          </details>
        )}
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
