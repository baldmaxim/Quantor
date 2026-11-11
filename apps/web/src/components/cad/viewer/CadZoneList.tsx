'use client';

import { useState, type FC, type ReactNode } from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import { CadRoomTypeSelect } from '@/components/cad/finishes/CadRoomTypeSelect';
import { CadZoneFinishBar } from '@/components/cad/finishes/CadZoneFinishBar';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { Button, cx } from '@/components/ui';
import type { IWorkspaceCadZoneFinish } from '@/components/workspace/cad/types';
import type { RoomType } from '@/lib/cad/room-types';
import { canSplitZoneKind } from '@/lib/cad/zone-split';
import {
  PARKING_TYPE_LABELS,
  ZONE_KIND_LABELS,
  doorSizeText,
  formatZoneArea,
  formatZoneLength,
  groupZones,
  parkingSummary,
  zoneUndefinedReason,
  type IZoneSum,
  type ParkingType,
} from '@/lib/cad/zones';

import { ParkingTypeSelect } from './ParkingTypeSelect';

interface ICadZoneListProps {
  zones: readonly CadZoneRead[];
  activeId: string | null;
  saving: boolean;
  onActivate: (id: string | null) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  /** Сменить тип у машино-места; не передан - тип в списке не правится. */
  onSetParkingType?: (id: string, type: ParkingType) => void;
  /** Сменить тип помещения у зоны; не передан - тип в списке не правится. */
  onSetRoomType?: (id: string, type: RoomType | null) => void;
  /** Выбор зон и назначение шаблона отделки; не передан - выбора нет. */
  finish?: IWorkspaceCadZoneFinish | null;
  /** Включён режим правки контура или разреза; пока он идёт, кнопки запуска не нужны. */
  shapeBusy?: boolean;
  /** Почему править контур нельзя; `null` - можно. */
  shapeDisabledReason?: string | null;
  onStartEdit?: (id: string) => void;
  onStartSplit?: (id: string) => void;
}

const sumText = (sum: IZoneSum): string =>
  `${formatZoneArea(sum.areaM2)}${sum.partial ? ' (не у всех)' : ''}`;

/** Название строки: марка и имя, а без них - вид зоны. */
const zoneTitle = (zone: CadZoneRead): string => {
  const parts = [zone.room_mark, zone.name].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(' · ') : ZONE_KIND_LABELS[zone.kind];
};

const zoneValues = (zone: CadZoneRead): string => {
  if (zone.kind === 'door') return doorSizeText(zone);
  const reason = zoneUndefinedReason(zone);
  if (reason !== null) return reason;
  const measures = `${formatZoneArea(zone.area_m2)} · периметр ${formatZoneLength(zone.perimeter_m)}`;
  return zone.kind === 'parking_space'
    ? `${PARKING_TYPE_LABELS[zone.parking_type ?? 'unknown']} · ${measures}`
    : measures;
};

interface IGroupProps {
  title: string;
  summary: string;
  children: ReactNode;
}

const Group: FC<IGroupProps> = ({ title, summary, children }) => (
  <section className="flex min-w-0 flex-col gap-[var(--s-2)]">
    <h4 className="flex items-baseline justify-between gap-[var(--s-3)] text-xs font-semibold">
      <span>{title}</span>
      <span className="text-muted">{summary}</span>
    </h4>
    <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">{children}</ul>
  </section>
);

/**
 * Список зон листа группами: «Квартира NNNN» (сумма площади), «МОП» (сумма), «Двери» (количество,
 * ширина × высота). Строка: выделить на холсте, переименовать, удалить с подтверждением.
 */
export const CadZoneList: FC<ICadZoneListProps> = ({
  zones,
  activeId,
  saving,
  onActivate,
  onRename,
  onDelete,
  onSetParkingType,
  onSetRoomType,
  finish = null,
  shapeBusy = false,
  shapeDisabledReason = null,
  onStartEdit,
  onStartSplit,
}) => {
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const groups = groupZones(zones);
  // Отделка есть у помещений квартир и МОП; у двери и машино-места её нет.
  const roomZones = zones.filter(
    (zone) => zone.kind === 'room_apartment' || zone.kind === 'room_mop',
  );
  const toggleChecked = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  const row = (zone: CadZoneRead) => {
    const active = zone.id === activeId;
    return (
      <li
        key={zone.id}
        className={cx(
          'flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border p-[var(--s-3)]',
          active ? 'border-accent bg-surface-muted' : 'border-border',
        )}
      >
        {editing?.id === zone.id ? (
          <form
            className="flex min-w-0 items-center gap-[var(--s-2)]"
            onSubmit={(event) => {
              event.preventDefault();
              onRename(zone.id, editing.name);
              setEditing(null);
            }}
          >
            <ClearableInput
              label="Название зоны"
              value={editing.name}
              maxLength={200}
              autoFocus
              wrapperClassName="min-w-0 flex-1"
              onChange={(event) => setEditing({ id: zone.id, name: event.target.value })}
              onClear={() => setEditing({ id: zone.id, name: '' })}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setEditing(null);
              }}
            />
            <Button type="submit" compact disabled={saving} className="max-md:h-[44px]">
              Сохранить
            </Button>
          </form>
        ) : (
          <div className="flex min-w-0 items-start gap-[var(--s-2)]">
            {finish !== null && (zone.kind === 'room_apartment' || zone.kind === 'room_mop') && (
              <label className="-m-[var(--s-2)] grid h-[44px] w-[44px] shrink-0 cursor-pointer place-items-center">
                <input
                  type="checkbox"
                  aria-label={`Выбрать зону: ${zoneTitle(zone)}`}
                  checked={checked.has(zone.id)}
                  onChange={() => toggleChecked(zone.id)}
                  className="h-[18px] w-[18px] accent-[var(--accent)]"
                />
              </label>
            )}
            <button
              type="button"
              aria-pressed={active}
              onClick={() => onActivate(active ? null : zone.id)}
              className="flex min-w-0 flex-1 flex-col items-start gap-[2px] text-left"
            >
              <span className="min-w-0 text-sm break-words">{zoneTitle(zone)}</span>
              <span className="text-xs text-muted">{zoneValues(zone)}</span>
            </button>
          </div>
        )}

        {onSetRoomType &&
          (zone.kind === 'room_apartment' || zone.kind === 'room_mop') &&
          editing?.id !== zone.id && (
            <CadRoomTypeSelect
              kind={zone.kind}
              label={`Тип помещения: ${zoneTitle(zone)}`}
              value={zone.room_type}
              source={zone.room_type_source}
              disabled={saving}
              onChange={(type) => onSetRoomType(zone.id, type)}
            />
          )}

        {zone.kind === 'parking_space' && onSetParkingType && editing?.id !== zone.id && (
          <ParkingTypeSelect
            label={`Тип места: ${zoneTitle(zone)}`}
            value={zone.parking_type ?? 'unknown'}
            disabled={saving}
            onChange={(type) => onSetParkingType(zone.id, type)}
          />
        )}

        {confirming === zone.id ? (
          <div className="flex flex-wrap items-center gap-[var(--s-2)]" role="alert">
            <span className="text-xs">Удалить зону?</span>
            <Button
              compact
              variant="danger"
              disabled={saving}
              className="max-md:h-[44px]"
              onClick={() => {
                onDelete(zone.id);
                setConfirming(null);
              }}
            >
              Удалить
            </Button>
            <Button compact className="max-md:h-[44px]" onClick={() => setConfirming(null)}>
              Отмена
            </Button>
          </div>
        ) : (
          editing?.id !== zone.id && (
            <div className="flex flex-wrap gap-[var(--s-2)]">
              <Button
                compact
                variant="ghost"
                className="max-md:h-[44px]"
                onClick={() => setEditing({ id: zone.id, name: zone.name ?? '' })}
              >
                Переименовать
              </Button>
              <Button
                compact
                variant="ghost"
                className="max-md:h-[44px]"
                onClick={() => setConfirming(zone.id)}
              >
                Удалить
              </Button>
              {active && zone.kind !== 'door' && onStartEdit && (
                <Button
                  compact
                  variant="ghost"
                  disabled={shapeBusy || shapeDisabledReason !== null}
                  title={shapeDisabledReason ?? undefined}
                  className="max-md:h-[44px]"
                  onClick={() => onStartEdit(zone.id)}
                >
                  Изменить контур
                </Button>
              )}
              {active && canSplitZoneKind(zone.kind) && onStartSplit && (
                <Button
                  compact
                  variant="ghost"
                  disabled={shapeBusy || shapeDisabledReason !== null}
                  title={shapeDisabledReason ?? undefined}
                  className="max-md:h-[44px]"
                  onClick={() => onStartSplit(zone.id)}
                >
                  Разрезать
                </Button>
              )}
            </div>
          )
        )}
      </li>
    );
  };

  if (zones.length === 0) {
    return <p className="text-xs text-muted">На этом листе зон пока нет.</p>;
  }

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="cad-zone-list">
      {finish !== null && roomZones.length > 0 && (
        <CadZoneFinishBar
          zones={roomZones}
          checked={checked}
          onCheckedChange={setChecked}
          templates={finish.templates}
          assigning={finish.assigning}
          error={finish.error}
          onAssign={finish.onAssign}
        />
      )}
      {groups.apartments.map((group) => (
        <Group
          key={group.apartmentNo}
          title={`Квартира ${group.apartmentNo}`}
          summary={sumText(group)}
        >
          {group.zones.map(row)}
        </Group>
      ))}
      {groups.mop.zones.length > 0 && (
        <Group title="МОП" summary={sumText(groups.mop)}>
          {groups.mop.zones.map(row)}
        </Group>
      )}
      {groups.parking.zones.length > 0 && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]" data-testid="cad-parking-summary">
          <Group
            title={`Машино-места: ${groups.parking.zones.length}`}
            summary={sumText(groups.parking)}
          >
            {parkingSummary(zones).map((item) => (
              <li
                key={item.type}
                className="flex items-baseline justify-between gap-[var(--s-3)] text-xs"
              >
                <span className="min-w-0 break-words">{PARKING_TYPE_LABELS[item.type]}</span>
                <span className="shrink-0 text-muted">
                  {item.count} шт. · {sumText(item)}
                </span>
              </li>
            ))}
          </Group>
          <Group title="Места на плане" summary="">
            {groups.parking.zones.map(row)}
          </Group>
        </div>
      )}
      {groups.doors.length > 0 && (
        <Group title="Двери" summary={`${groups.doors.length} шт.`}>
          {groups.doors.map(row)}
        </Group>
      )}
    </div>
  );
};
