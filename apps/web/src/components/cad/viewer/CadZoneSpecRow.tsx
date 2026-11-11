'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import { CadRoomTypeSelect } from '@/components/cad/finishes/CadRoomTypeSelect';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { Button, cx } from '@/components/ui';
import { ROOM_TYPE_LABELS, type RoomType } from '@/lib/cad/room-types';
import { canSplitZoneKind } from '@/lib/cad/zone-split';
import { zoneSpecValue, zoneTitle, type ParkingType } from '@/lib/cad/zones';

import { ParkingTypeSelect } from './ParkingTypeSelect';

interface ICadZoneSpecRowProps {
  zone: CadZoneRead;
  active: boolean;
  saving: boolean;
  /** Показывать флажок выбора (режим назначения шаблона отделки). */
  selectable: boolean;
  checked: boolean;
  onToggleChecked: (id: string) => void;
  onActivate: (id: string | null) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onSetParkingType?: (id: string, type: ParkingType) => void;
  onSetRoomType?: (id: string, type: RoomType | null) => void;
  shapeBusy: boolean;
  shapeDisabledReason: string | null;
  onStartEdit?: (id: string) => void;
  onStartSplit?: (id: string) => void;
}

const roomTypeText = (zone: CadZoneRead): string | null => {
  if (zone.room_type === null) return null;
  const label = ROOM_TYPE_LABELS[zone.room_type];
  return zone.room_type_source === 'derived' ? `${label} · авто` : label;
};

/**
 * Строка спецификации зоны: марка, название, тип и площадь в одну линию; вся строка выделяет зону
 * на холсте. Действия - только у выделенной зоны, под строкой.
 */
export const CadZoneSpecRow: FC<ICadZoneSpecRowProps> = ({
  zone,
  active,
  saving,
  selectable,
  checked,
  onToggleChecked,
  onActivate,
  onRename,
  onDelete,
  onSetParkingType,
  onSetRoomType,
  shapeBusy,
  shapeDisabledReason,
  onStartEdit,
  onStartSplit,
}) => {
  const [editingName, setEditingName] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [prevActive, setPrevActive] = useState(active);
  const rowRef = useRef<HTMLLIElement>(null);

  // Сняли выделение - форма и подтверждение закрываются.
  if (active !== prevActive) {
    setPrevActive(active);
    if (!active) {
      setEditingName(null);
      setConfirming(false);
    }
  }

  useEffect(() => {
    const node = rowRef.current;
    if (active && node !== null && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' });
    }
  }, [active]);

  const isRoom = zone.kind === 'room_apartment' || zone.kind === 'room_mop';
  const typeText = roomTypeText(zone);
  const title = zoneTitle(zone);

  return (
    <li
      ref={rowRef}
      className={cx(
        'flex min-w-0 flex-col border-b border-l-2 border-border',
        active ? 'border-l-accent bg-surface-muted' : 'border-l-transparent',
      )}
    >
      <div className="flex min-w-0 items-stretch">
        {selectable && isRoom && (
          <label className="grid h-[44px] w-[44px] shrink-0 cursor-pointer place-items-center">
            <input
              type="checkbox"
              aria-label={`Выбрать зону: ${title}`}
              checked={checked}
              onChange={() => onToggleChecked(zone.id)}
              className="h-[18px] w-[18px] accent-[var(--accent)]"
            />
          </label>
        )}
        <button
          type="button"
          aria-pressed={active}
          onClick={() => onActivate(active ? null : zone.id)}
          className="flex min-w-0 flex-1 items-start justify-between gap-[var(--s-3)] px-[var(--s-2)] py-[var(--s-2)] text-left max-md:min-h-[44px]"
        >
          <span className="flex min-w-0 flex-col gap-[2px]">
            <span className="min-w-0 text-sm break-words">{title}</span>
            {typeText !== null && <span className="text-xs text-muted">{typeText}</span>}
          </span>
          <span className="shrink-0 text-right text-xs text-muted">{zoneSpecValue(zone)}</span>
        </button>
      </div>

      {active && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)] px-[var(--s-2)] pb-[var(--s-3)]">
          {editingName !== null ? (
            <form
              className="flex min-w-0 items-center gap-[var(--s-2)]"
              onSubmit={(event) => {
                event.preventDefault();
                onRename(zone.id, editingName);
                setEditingName(null);
              }}
            >
              <ClearableInput
                label="Название зоны"
                value={editingName}
                maxLength={200}
                autoFocus
                wrapperClassName="min-w-0 flex-1"
                onChange={(event) => setEditingName(event.target.value)}
                onClear={() => setEditingName('')}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') setEditingName(null);
                }}
              />
              <Button type="submit" compact disabled={saving} className="max-md:h-[44px]">
                Сохранить
              </Button>
            </form>
          ) : (
            <>
              {onSetRoomType && isRoom && (
                <CadRoomTypeSelect
                  kind={zone.kind}
                  label={`Тип помещения: ${title}`}
                  value={zone.room_type}
                  source={zone.room_type_source}
                  disabled={saving}
                  onChange={(type) => onSetRoomType(zone.id, type)}
                />
              )}
              {zone.kind === 'parking_space' && onSetParkingType && (
                <ParkingTypeSelect
                  label={`Тип места: ${title}`}
                  value={zone.parking_type ?? 'unknown'}
                  disabled={saving}
                  onChange={(type) => onSetParkingType(zone.id, type)}
                />
              )}
              {confirming ? (
                <div className="flex flex-wrap items-center gap-[var(--s-2)]" role="alert">
                  <span className="text-xs">Удалить зону?</span>
                  <Button
                    compact
                    variant="danger"
                    disabled={saving}
                    className="max-md:h-[44px]"
                    onClick={() => {
                      onDelete(zone.id);
                      setConfirming(false);
                    }}
                  >
                    Удалить
                  </Button>
                  <Button compact className="max-md:h-[44px]" onClick={() => setConfirming(false)}>
                    Отмена
                  </Button>
                </div>
              ) : (
                <div className="flex flex-wrap gap-[var(--s-2)]">
                  <Button
                    compact
                    variant="ghost"
                    className="max-md:h-[44px]"
                    onClick={() => setEditingName(zone.name ?? '')}
                  >
                    Переименовать
                  </Button>
                  <Button
                    compact
                    variant="ghost"
                    className="max-md:h-[44px]"
                    onClick={() => setConfirming(true)}
                  >
                    Удалить
                  </Button>
                  {zone.kind !== 'door' && onStartEdit && (
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
                  {canSplitZoneKind(zone.kind) && onStartSplit && (
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
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
};
