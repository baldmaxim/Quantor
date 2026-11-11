'use client';

import { useState, type FC } from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import { CadZoneFinishBar } from '@/components/cad/finishes/CadZoneFinishBar';
import { Button } from '@/components/ui';
import type { IWorkspaceCadZoneFinish } from '@/components/workspace/cad/types';
import type { RoomType } from '@/lib/cad/room-types';
import {
  DOORS_GROUP_KEY,
  MOP_GROUP_KEY,
  PARKING_GROUP_KEY,
  PARKING_TYPE_LABELS,
  apartmentGroupKey,
  formatZoneSum,
  groupZones,
  parkingSummary,
  zoneGroupKey,
  zoneGroupKeys,
  zoneListSummary,
  type ParkingType,
} from '@/lib/cad/zones';

import { CadZoneSpecGroup, type ZoneGroupSelection } from './CadZoneSpecGroup';
import { CadZoneSpecRow } from './CadZoneSpecRow';

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

const ROW_LIST = 'm-0 flex list-none flex-col p-0';

/**
 * Спецификация зон листа: сводка сверху и сворачиваемые группы (квартиры, МОП, машино-места,
 * двери). По умолчанию всё свёрнуто; действия есть только у выделенной зоны.
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
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const [selecting, setSelecting] = useState(false);
  const [seenActiveId, setSeenActiveId] = useState<string | null>(null);

  // Выделили зону (в том числе щелчком по холсту) - её группа раскрывается.
  if (activeId !== seenActiveId) {
    setSeenActiveId(activeId);
    const activeZone = activeId === null ? undefined : zones.find((zone) => zone.id === activeId);
    if (activeZone !== undefined) {
      setExpanded(new Set([...expanded, zoneGroupKey(activeZone)]));
    }
  }

  const groups = groupZones(zones);
  // Отделка есть у помещений квартир и МОП; у двери и машино-места её нет.
  const roomZones = zones.filter(
    (zone) => zone.kind === 'room_apartment' || zone.kind === 'room_mop',
  );
  const showFinish = finish !== null && roomZones.length > 0;
  const selectMode = showFinish && selecting;

  const toggleGroup = (key: string) => {
    const next = new Set(expanded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setExpanded(next);
  };
  const toggleChecked = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };
  const selectionState = (items: readonly CadZoneRead[]): ZoneGroupSelection => {
    const count = items.filter((zone) => checked.has(zone.id)).length;
    if (count === 0) return 'none';
    return count === items.length ? 'all' : 'some';
  };
  const groupSelection = (title: string, items: readonly CadZoneRead[]) => {
    if (!selectMode) return null;
    const state = selectionState(items);
    return {
      state,
      label: `Выбрать все помещения: ${title}`,
      onToggle: () => {
        const next = new Set(checked);
        for (const zone of items) {
          if (state === 'all') next.delete(zone.id);
          else next.add(zone.id);
        }
        setChecked(next);
      },
    };
  };

  const row = (zone: CadZoneRead) => (
    <CadZoneSpecRow
      key={zone.id}
      zone={zone}
      active={zone.id === activeId}
      saving={saving}
      selectable={selectMode}
      checked={checked.has(zone.id)}
      onToggleChecked={toggleChecked}
      onActivate={onActivate}
      onRename={onRename}
      onDelete={onDelete}
      onSetParkingType={onSetParkingType}
      onSetRoomType={onSetRoomType}
      shapeBusy={shapeBusy}
      shapeDisabledReason={shapeDisabledReason}
      onStartEdit={onStartEdit}
      onStartSplit={onStartSplit}
    />
  );

  if (zones.length === 0) {
    return <p className="text-xs text-muted">На этом листе зон пока нет.</p>;
  }

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]" data-testid="cad-zone-list">
      <div className="flex min-w-0 flex-col gap-[2px] text-xs" data-testid="cad-zone-summary">
        {zoneListSummary(groups).map((line) => (
          <p key={line} className="m-0 break-words">
            {line}
          </p>
        ))}
      </div>
      <div className="flex flex-wrap gap-[var(--s-2)]">
        <Button
          compact
          variant="ghost"
          className="max-md:h-[44px]"
          onClick={() => setExpanded(new Set(zoneGroupKeys(groups)))}
        >
          Развернуть все
        </Button>
        <Button
          compact
          variant="ghost"
          className="max-md:h-[44px]"
          onClick={() => setExpanded(new Set())}
        >
          Свернуть все
        </Button>
        {showFinish && (
          <Button
            compact
            variant="ghost"
            className="max-md:h-[44px]"
            onClick={() => {
              setSelecting(!selecting);
              setChecked(new Set());
            }}
          >
            {selecting ? 'Готово' : 'Шаблон отделки…'}
          </Button>
        )}
      </div>

      {selectMode && finish !== null && (
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

      {groups.apartments.map((group) => {
        const key = apartmentGroupKey(group.apartmentNo);
        const title = group.apartmentNo === '' ? 'Кв. без номера' : `Кв. ${group.apartmentNo}`;
        return (
          <CadZoneSpecGroup
            key={key}
            title={title}
            summary={`${group.zones.length} пом. · ${formatZoneSum(group)}`}
            expanded={expanded.has(key)}
            onToggle={() => toggleGroup(key)}
            selection={groupSelection(title, group.zones)}
          >
            <ul className={ROW_LIST}>{group.zones.map(row)}</ul>
          </CadZoneSpecGroup>
        );
      })}
      {groups.mop.zones.length > 0 && (
        <CadZoneSpecGroup
          title="МОП"
          summary={`${groups.mop.zones.length} пом. · ${formatZoneSum(groups.mop)}`}
          expanded={expanded.has(MOP_GROUP_KEY)}
          onToggle={() => toggleGroup(MOP_GROUP_KEY)}
          selection={groupSelection('МОП', groups.mop.zones)}
        >
          <ul className={ROW_LIST}>{groups.mop.zones.map(row)}</ul>
        </CadZoneSpecGroup>
      )}
      {groups.parking.zones.length > 0 && (
        <CadZoneSpecGroup
          title={`Машино-места: ${groups.parking.zones.length}`}
          summary={formatZoneSum(groups.parking)}
          expanded={expanded.has(PARKING_GROUP_KEY)}
          onToggle={() => toggleGroup(PARKING_GROUP_KEY)}
        >
          <ul
            className="m-0 flex list-none flex-col gap-[2px] border-b border-border p-[var(--s-2)]"
            data-testid="cad-parking-summary"
          >
            {parkingSummary(zones).map((item) => (
              <li
                key={item.type}
                className="flex items-baseline justify-between gap-[var(--s-3)] text-xs"
              >
                <span className="min-w-0 break-words">{PARKING_TYPE_LABELS[item.type]}</span>
                <span className="shrink-0 text-muted">
                  {item.count} шт. · {formatZoneSum(item)}
                </span>
              </li>
            ))}
          </ul>
          <ul className={ROW_LIST}>{groups.parking.zones.map(row)}</ul>
        </CadZoneSpecGroup>
      )}
      {groups.doors.length > 0 && (
        <CadZoneSpecGroup
          title={`Двери: ${groups.doors.length} шт.`}
          expanded={expanded.has(DOORS_GROUP_KEY)}
          onToggle={() => toggleGroup(DOORS_GROUP_KEY)}
        >
          <ul className={ROW_LIST}>{groups.doors.map(row)}</ul>
        </CadZoneSpecGroup>
      )}
    </div>
  );
};
