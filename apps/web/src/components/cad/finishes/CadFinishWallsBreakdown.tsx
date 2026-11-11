'use client';

import type { FC } from 'react';

import type { CadFinishZoneRead } from '@quantor/api-client';

import { cx } from '@/components/ui';
import {
  DASH,
  WALLS_UNLINKED_LABEL,
  finishZoneTitle,
  formatFinishArea,
  formatFinishMeters,
} from '@/lib/cad/finish-sheet';
import { FINISH_BASES, FINISH_BASE_LABELS } from '@/lib/cad/room-types';

import { NUM, TD, TH } from './finish-table-styles';

interface ICadFinishWallsBreakdownProps {
  zone: CadFinishZoneRead;
}

/**
 * Блок «Стены по участкам» раскрытой строки зоны (ADR-0042, п. 6): монолит, кладка, ГКЛ,
 * двери (надпроёмная часть), проёмы без двери, участки без стены, откосы. Не привязано к
 * конструкциям - одна пометка, величин нет. Не определено - «—», не 0.
 */
export const CadFinishWallsBreakdown: FC<ICadFinishWallsBreakdownProps> = ({ zone }) => {
  const breakdown = zone.walls_breakdown;
  const title = finishZoneTitle(zone);

  if (!breakdown.linked) {
    return (
      <section
        aria-label={`Стены по участкам: ${title}`}
        className="flex flex-col gap-[var(--s-1)]"
      >
        <h4 className="text-xs font-semibold">Стены по участкам</h4>
        <p className="text-xs text-muted">{WALLS_UNLINKED_LABEL}</p>
      </section>
    );
  }

  const baseLengths = {
    monolith: breakdown.monolith_m,
    masonry: breakdown.masonry_m,
    gkl: breakdown.gkl_m,
  } as const;

  return (
    <section aria-label={`Стены по участкам: ${title}`} className="flex flex-col gap-[var(--s-1)]">
      <h4 className="text-xs font-semibold">Стены по участкам</h4>
      <table className="w-full border-collapse text-xs" aria-label={`Участки стен зоны: ${title}`}>
        <thead>
          <tr>
            <th className={TH}>Участок</th>
            <th className={cx(TH, 'text-right')}>Длина, м</th>
            <th className={cx(TH, 'text-right')}>Площадь, м²</th>
          </tr>
        </thead>
        <tbody>
          {FINISH_BASES.map((base) => (
            <tr key={base} className="border-t border-border">
              <td className={TD}>{FINISH_BASE_LABELS[base]}</td>
              <td className={NUM}>{formatFinishMeters(baseLengths[base])}</td>
              <td className={NUM}>{formatFinishArea(breakdown.area_by_base[base])}</td>
            </tr>
          ))}
          <tr className="border-t border-border">
            <td className={TD}>Двери (над проёмами)</td>
            <td className={NUM}>{formatFinishMeters(breakdown.door_m)}</td>
            <td className={NUM}>{formatFinishArea(breakdown.door_over_area_m2)}</td>
          </tr>
          <tr className="border-t border-border">
            <td className={TD}>Проёмы без двери</td>
            <td className={NUM}>{formatFinishMeters(breakdown.gap_m)}</td>
            <td className={NUM}>{DASH}</td>
          </tr>
          <tr className="border-t border-border">
            <td className={TD}>Без стены</td>
            <td className={NUM}>{formatFinishMeters(breakdown.open_m)}</td>
            <td className={NUM}>{DASH}</td>
          </tr>
          <tr className="border-t border-border">
            <td className={TD}>Откосы</td>
            <td className={NUM}>{formatFinishMeters(breakdown.reveal_m)}</td>
            <td className={NUM}>{formatFinishArea(breakdown.reveal_area_m2)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
};
