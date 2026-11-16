'use client';

import type { CadZoneRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions, StatusBadge } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import {
  useAcceptCadZone,
  useCadZonesSummary,
  useDeleteCadZonesOfSheet,
  type ZonesDeleteScope,
} from '@/lib/cad/zones-quality-queries';
import { ZONE_QUALITY_LABELS, zoneQualityTone, zonesOutOfTolerance } from '@/lib/cad/zone-quality';
import { zoneTitle } from '@/lib/cad/zones';

/**
 * Сверка зон листа с экспликацией в разделе «Зоны»: сколько зон в допуске, на проверке и
 * отклонено, сумма по квартирам против экспликации, марки без зоны и список зон вне допуска с
 * причиной и принятием. Отклонённая зона не участвует в плите, перегородках и отделке, пока её
 * не примет человек. Здесь же - пересоздание авто-зон и массовое удаление зон листа.
 */

export interface ICadZonesQualityProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  /** Раздел «Зоны» открыт: без этого сводка не запрашивается. */
  readonly load: boolean;
  readonly zones: readonly CadZoneRead[];
  readonly activeId: string | null;
  readonly onActivate: (id: string | null) => void;
  /** Запуск авторазметки (пересоздание авто-зон); `null` - запускать нечего. */
  readonly recreate: { readonly onStart: () => void; readonly starting: boolean } | null;
}

type Confirm = ZonesDeleteScope | 'recreate';

const CONFIRM_TEXT: Readonly<Record<Confirm, { title: string; action: string; body: string }>> = {
  auto: {
    title: 'Удалить авто-зоны листа?',
    action: 'Удалить авто-зоны',
    body: 'Будут удалены зоны, созданные авторазметкой и не тронутые человеком. Зоны, созданные, правленные или принятые человеком, останутся.',
  },
  all: {
    title: 'Удалить все зоны листа?',
    action: 'Удалить все зоны',
    body: 'Будут удалены все зоны листа, включая разметку человека, двери и машино-места. Действие необратимо.',
  },
  recreate: {
    title: 'Разметить зоны листа заново?',
    action: 'Разметить заново',
    body: 'Все зоны листа созданы авторазметкой: они будут удалены и построены заново текущей версией генератора.',
  },
};

const TAP = 'max-md:h-[44px]';

const area = (value: number | null | undefined): string =>
  value == null ? '—' : `${value.toFixed(1).replace('.', ',')} м²`;

const percent = (value: number | null | undefined): string =>
  value == null ? '' : ` (${value > 0 ? '+' : ''}${value.toFixed(1).replace('.', ',')} %)`;

export const CadZonesQuality: FC<ICadZonesQualityProps> = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  zones,
  activeId,
  onActivate,
  recreate,
}) => {
  const summary = useCadZonesSummary(projectId, revisionId, pageIndex, load && zones.length > 0);
  const accept = useAcceptCadZone(projectId);
  const remove = useDeleteCadZonesOfSheet(projectId, revisionId, pageIndex);
  const [confirming, setConfirming] = useState<Confirm | null>(null);
  const [marksOpen, setMarksOpen] = useState(false);

  if (zones.length === 0) return null;

  const data = summary.data;
  const problems = zonesOutOfTolerance(zones);
  const failure = accept.error ?? remove.error;
  const busy = accept.isPending || remove.isPending;

  const confirm = () => {
    if (confirming === 'recreate') recreate?.onStart();
    else if (confirming !== null) remove.mutate(confirming);
    setConfirming(null);
  };

  return (
    <section
      aria-label="Сверка зон с экспликацией"
      data-testid="cad-zones-quality"
      className="flex min-w-0 flex-col gap-[var(--s-3)] border-b border-border pb-[var(--s-4)]"
    >
      {data && (
        <>
          <div className="flex min-w-0 flex-wrap items-center gap-[var(--s-2)]">
            <StatusBadge tone="success" wrap>{`в допуске: ${data.ok}`}</StatusBadge>
            {data.review > 0 && (
              <StatusBadge tone="warning" wrap>{`на проверку: ${data.review}`}</StatusBadge>
            )}
            {data.failed > 0 && (
              <StatusBadge tone="danger" wrap>{`отклонено: ${data.failed}`}</StatusBadge>
            )}
          </div>
          <p className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
            {data.apartments_compared > 0
              ? `Квартиры: ${area(data.apartments_area_m2)} против ${area(data.apartments_expl_area_m2)} по экспликации${percent(data.apartments_delta_percent)}, зон в сверке: ${data.apartments_compared}`
              : 'Квартиры: нет данных экспликации для сверки'}
          </p>
          <p className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
            {`Авто: ${data.auto} · человек: ${data.human}`}
            {data.unknown > 0 && ` · происхождение неизвестно: ${data.unknown}`}
            {data.generator_versions.length > 0 && ` · ${data.generator_versions.join(', ')}`}
          </p>
          {data.unmatched_marks.length > 0 && (
            <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
              <Button
                compact
                variant="ghost"
                aria-expanded={marksOpen}
                className={`self-start ${TAP}`}
                onClick={() => setMarksOpen((value) => !value)}
              >
                {`Марки без зоны: ${data.unmatched_marks.length}`}
              </Button>
              {marksOpen && (
                <ul className="m-0 list-none p-0 text-xs text-muted">
                  {data.unmatched_marks.map((mark) => (
                    <li
                      key={`${mark.room_mark}:${mark.reason ?? ''}`}
                      className="[overflow-wrap:anywhere]"
                    >
                      {[
                        mark.room_mark,
                        mark.name,
                        mark.expl_area_m2 == null ? null : area(mark.expl_area_m2),
                        mark.reason,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
      {summary.isError && (
        <p role="alert" className="m-0 text-xs text-danger">
          Не удалось загрузить сверку зон с экспликацией.
        </p>
      )}

      {problems.length > 0 && (
        <ul
          className="m-0 flex max-h-[40dvh] list-none flex-col overflow-auto overscroll-contain p-0"
          aria-label="Зоны вне допуска"
        >
          {problems.map((zone) => (
            <li
              key={zone.id}
              className="flex min-w-0 flex-wrap items-center justify-between gap-[var(--s-2)] border-t border-border py-[var(--s-2)]"
            >
              <button
                type="button"
                aria-pressed={activeId === zone.id}
                onClick={() => onActivate(activeId === zone.id ? null : zone.id)}
                className="flex min-w-0 flex-1 flex-col items-start gap-[2px] text-left max-md:min-h-[44px]"
              >
                <span className="flex min-w-0 flex-wrap items-center gap-[var(--s-2)]">
                  <StatusBadge tone={zoneQualityTone(zone.quality_status)} wrap>
                    {ZONE_QUALITY_LABELS[zone.quality_status]}
                  </StatusBadge>
                  <span className="min-w-0 text-sm break-words">{zoneTitle(zone)}</span>
                </span>
                {zone.quality_reason && (
                  <span className="text-xs text-muted [overflow-wrap:anywhere]">
                    {zone.quality_reason}
                  </span>
                )}
              </button>
              <Button
                compact
                disabled={busy}
                className={TAP}
                aria-label={`Принять зону: ${zoneTitle(zone)}`}
                onClick={() => accept.mutate(zone.id)}
              >
                Принять
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex min-w-0 flex-wrap gap-[var(--s-2)]">
        {recreate !== null && data?.recreate_allowed === true && (
          <Button
            compact
            loading={recreate.starting}
            disabled={busy}
            className={TAP}
            onClick={() => setConfirming('recreate')}
          >
            Разметить заново
          </Button>
        )}
        {(data?.auto ?? 0) > 0 && (
          <Button
            compact
            variant="ghost"
            disabled={busy}
            className={TAP}
            onClick={() => setConfirming('auto')}
          >
            Удалить авто-зоны
          </Button>
        )}
        <Button
          compact
          variant="ghost"
          disabled={busy}
          className={TAP}
          onClick={() => setConfirming('all')}
        >
          Удалить все зоны
        </Button>
      </div>
      {failure != null && (
        <p role="alert" className="m-0 text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(failure)}
        </p>
      )}

      <Dialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        title={confirming ? CONFIRM_TEXT[confirming].title : ''}
        footer={
          <DialogActions>
            <Button onClick={() => setConfirming(null)}>Отмена</Button>
            <Button variant={confirming === 'recreate' ? 'primary' : 'danger'} onClick={confirm}>
              {confirming ? CONFIRM_TEXT[confirming].action : ''}
            </Button>
          </DialogActions>
        }
      >
        <p className="text-sm">{confirming ? CONFIRM_TEXT[confirming].body : ''}</p>
      </Dialog>
    </section>
  );
};
