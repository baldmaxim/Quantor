'use client';

import { useState, type FC } from 'react';

import type { CadFinishWarningRead, CadFinishZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { WARNING_ZONES_PREVIEW, finishZoneTitle, warningZoneIds } from '@/lib/cad/finish-sheet';
import { FINISH_WARNING_LABELS } from '@/lib/cad/room-types';

interface ICadFinishWarningsProps {
  warnings: readonly CadFinishWarningRead[];
  zones: readonly CadFinishZoneRead[];
  /** Выделить зону на листе, как выбор в списке зон. */
  onActivate: (id: string | null) => void;
}

const Warning: FC<{
  warning: CadFinishWarningRead;
  zones: readonly CadFinishZoneRead[];
  onActivate: (id: string | null) => void;
}> = ({ warning, zones, onActivate }) => {
  const [expanded, setExpanded] = useState(false);
  const shown = warningZoneIds(warning, expanded);
  const hidden = warning.zone_ids.length - shown.length;
  const titleOf = (id: string): string => {
    const zone = zones.find((item) => item.zone_id === id);
    return zone === undefined ? 'зона' : finishZoneTitle(zone);
  };

  return (
    <li className="flex min-w-0 flex-col gap-[var(--s-1)]">
      <span className="text-xs">
        {FINISH_WARNING_LABELS[warning.code]}
        {warning.zone_ids.length > 0 && ` (зон: ${warning.zone_ids.length})`}
      </span>
      {shown.length > 0 && (
        <span className="flex flex-wrap gap-x-[var(--s-3)]">
          {shown.map((id) => (
            <button
              key={id}
              type="button"
              aria-label={`Выделить зону: ${titleOf(id)}`}
              onClick={() => onActivate(id)}
              className="min-h-[44px] text-left text-xs text-accent underline-offset-2 hover:underline"
            >
              {titleOf(id)}
            </button>
          ))}
          {hidden > 0 && (
            <Button
              compact
              variant="ghost"
              className="max-md:h-[44px]"
              onClick={() => setExpanded(true)}
            >
              Ещё {hidden}
            </Button>
          )}
          {expanded && warning.zone_ids.length > WARNING_ZONES_PREVIEW && (
            <Button
              compact
              variant="ghost"
              className="max-md:h-[44px]"
              onClick={() => setExpanded(false)}
            >
              Свернуть
            </Button>
          )}
        </span>
      )}
    </li>
  );
};

/** Предупреждения ведомости; зоны в них - ссылки: клик выделяет зону на листе. */
export const CadFinishWarnings: FC<ICadFinishWarningsProps> = ({ warnings, zones, onActivate }) => {
  if (warnings.length === 0) return null;
  return (
    <section
      aria-label="Предупреждения ведомости"
      className="flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border p-[var(--s-3)]"
    >
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
        Предупреждения
      </h4>
      <ul className="m-0 flex list-none flex-col gap-[var(--s-3)] p-0">
        {warnings.map((warning) => (
          <Warning key={warning.code} warning={warning} zones={zones} onActivate={onActivate} />
        ))}
      </ul>
    </section>
  );
};
