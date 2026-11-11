'use client';

import type { FC } from 'react';

import type { CadFinishRoomTypeRead, CadFinishTotalRead } from '@quantor/api-client';

import { cx } from '@/components/ui';
import { DASH, formatFinishArea, formatMaterialQty } from '@/lib/cad/finish-sheet';
import { ROOM_TYPE_LABELS, SURFACE_LABELS } from '@/lib/cad/room-types';

import { NUM, TD, TH } from './finish-table-styles';

interface ICadFinishTotalsProps {
  totals: readonly CadFinishTotalRead[];
  byRoomType: readonly CadFinishRoomTypeRead[];
}

/** Итоги ведомости: по слоям (поверхность, работа, материал) и по типам помещений. */
export const CadFinishTotals: FC<ICadFinishTotalsProps> = ({ totals, byRoomType }) => (
  <div className="flex min-w-0 flex-col gap-[var(--s-5)]">
    <section aria-label="Итоги по слоям" className="flex min-w-0 flex-col gap-[var(--s-2)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
        Итоги по слоям
      </h4>
      {totals.length === 0 ? (
        <p className="text-xs text-muted">Итогов нет: слои не назначены.</p>
      ) : (
        <div className="scroll-area min-w-0 overflow-x-auto overscroll-x-contain">
          <table className="w-full min-w-[520px] border-collapse text-xs">
            <thead>
              <tr>
                <th className={TH}>Поверхность</th>
                <th className={TH}>Работа</th>
                <th className={TH}>Материал</th>
                <th className={cx(TH, 'text-right')}>Площадь, м²</th>
                <th className={cx(TH, 'text-right')}>Материал, кол-во</th>
                <th className={cx(TH, 'text-right')}>Зон</th>
              </tr>
            </thead>
            <tbody>
              {totals.map((total, index) => (
                <tr
                  key={`${total.surface}:${total.work}:${total.material ?? ''}:${index}`}
                  className="border-t border-border"
                >
                  <td className={TD}>{SURFACE_LABELS[total.surface]}</td>
                  <td className={TD}>{total.work}</td>
                  <td className={TD}>{total.material ?? DASH}</td>
                  <td className={NUM}>{formatFinishArea(total.area_m2)}</td>
                  <td className={NUM}>
                    {formatMaterialQty(total.material_qty, total.material_unit)}
                  </td>
                  <td className={NUM}>{total.zone_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>

    <section
      aria-label="Итоги по типам помещений"
      className="flex min-w-0 flex-col gap-[var(--s-2)]"
    >
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
        Итоги по типам помещений
      </h4>
      {byRoomType.length === 0 ? (
        <p className="text-xs text-muted">Типы помещений не заданы.</p>
      ) : (
        <div className="scroll-area min-w-0 overflow-x-auto overscroll-x-contain">
          <table className="w-full min-w-[420px] border-collapse text-xs">
            <thead>
              <tr>
                <th className={TH}>Тип</th>
                <th className={cx(TH, 'text-right')}>Зон</th>
                <th className={cx(TH, 'text-right')}>Пол, м²</th>
                <th className={cx(TH, 'text-right')}>Стены, м²</th>
                <th className={cx(TH, 'text-right')}>Потолок, м²</th>
              </tr>
            </thead>
            <tbody>
              {byRoomType.map((item) => (
                <tr key={item.room_type} className="border-t border-border">
                  <td className={TD}>{ROOM_TYPE_LABELS[item.room_type]}</td>
                  <td className={NUM}>{item.zone_count}</td>
                  <td className={NUM}>{formatFinishArea(item.floor_area_m2)}</td>
                  <td className={NUM}>{formatFinishArea(item.wall_area_m2)}</td>
                  <td className={NUM}>{formatFinishArea(item.ceiling_area_m2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  </div>
);
