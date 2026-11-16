'use client';

import type { FC } from 'react';

import type { CadFinishWarningRead, CadFinishZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { FINISH_WARNING_LABELS } from '@/lib/cad/room-types';

import { CadFinishZoneLinks } from './CadFinishZoneLinks';

interface ICadFinishWarningsProps {
  warnings: readonly CadFinishWarningRead[];
  zones: readonly CadFinishZoneRead[];
  /** Выделить зону на листе, как выбор в списке зон. */
  onActivate: (id: string | null) => void;
  /** Открыть раздел «Конструкции»: там высоты листа. Кнопка - у предупреждения о высоте стен. */
  onOpenConstructions?: () => void;
}

/** Предупреждения ведомости; зоны в них - ссылки: клик выделяет зону на листе. */
export const CadFinishWarnings: FC<ICadFinishWarningsProps> = ({
  warnings,
  zones,
  onActivate,
  onOpenConstructions,
}) => {
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
          <li key={warning.code} className="flex min-w-0 flex-col gap-[var(--s-1)]">
            <span className="text-xs break-words">
              {FINISH_WARNING_LABELS[warning.code]}
              {warning.zone_ids.length > 0 && ` (зон: ${warning.zone_ids.length})`}
            </span>
            <CadFinishZoneLinks zoneIds={warning.zone_ids} zones={zones} onActivate={onActivate} />
            {warning.code === 'wall_height_missing' && onOpenConstructions !== undefined && (
              <Button compact className="self-start max-md:h-[44px]" onClick={onOpenConstructions}>
                Открыть «Конструкции»
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
};
