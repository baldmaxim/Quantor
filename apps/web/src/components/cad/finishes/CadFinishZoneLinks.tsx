'use client';

import { useState, type FC } from 'react';

import type { CadFinishZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { WARNING_ZONES_PREVIEW, finishZoneTitle } from '@/lib/cad/finish-sheet';

interface ICadFinishZoneLinksProps {
  zoneIds: readonly string[];
  zones: readonly CadFinishZoneRead[];
  /** Выделить зону на листе, как выбор в списке зон. */
  onActivate: (id: string | null) => void;
}

/** Зоны ссылками: клик выделяет зону на листе. Сначала первые несколько, остальные - «и ещё K». */
export const CadFinishZoneLinks: FC<ICadFinishZoneLinksProps> = ({
  zoneIds,
  zones,
  onActivate,
}) => {
  const [expanded, setExpanded] = useState(false);
  if (zoneIds.length === 0) return null;
  const shown = expanded ? zoneIds : zoneIds.slice(0, WARNING_ZONES_PREVIEW);
  const hidden = zoneIds.length - shown.length;
  const titleOf = (id: string): string => {
    const zone = zones.find((item) => item.zone_id === id);
    return zone === undefined ? 'зона' : finishZoneTitle(zone);
  };

  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-3)]">
      {shown.map((id) => (
        <button
          key={id}
          type="button"
          aria-label={`Выделить зону: ${titleOf(id)}`}
          onClick={() => onActivate(id)}
          className="min-h-[44px] min-w-0 text-left text-xs break-words text-accent underline-offset-2 hover:underline"
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
          и ещё {hidden}
        </Button>
      )}
      {expanded && zoneIds.length > WARNING_ZONES_PREVIEW && (
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
  );
};
