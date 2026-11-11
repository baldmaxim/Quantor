'use client';

import { useState, type FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';
import { Button, SegmentedControl, Skeleton, type ISegmentedOption } from '@/components/ui';
import {
  DOOR_HEIGHT_MAX_MM,
  DOOR_HEIGHT_MIN_MM,
  ZONE_KINDS,
  ZONE_KIND_LABELS,
  hasRoomMark,
  type ZoneKind,
} from '@/lib/cad/zones';
import type { IWorkspaceCadZones } from '@/components/workspace/cad/types';

import { CadZoneList } from './CadZoneList';
import { ParkingTypeSelect } from './ParkingTypeSelect';

const KIND_OPTIONS: readonly ISegmentedOption<ZoneKind>[] = ZONE_KINDS.map((kind) => ({
  value: kind,
  label: ZONE_KIND_LABELS[kind],
}));

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';

/** Раздел «Зоны»: выбор вида и рисование на листе, затем список зон с суммами. */
export const CadZonesPanel: FC<IWorkspaceCadZones> = ({
  zones,
  loading,
  loadError,
  onReload,
  kind,
  onKindChange,
  apartmentNo,
  onApartmentNoChange,
  roomMark,
  onRoomMarkChange,
  doorHeight,
  onDoorHeightChange,
  parkingType,
  onParkingTypeChange,
  onSetParkingType,
  drawing,
  drawDisabledReason,
  onStartDrawing,
  onStopDrawing,
  activeId,
  onActivate,
  saving,
  error,
  onRename,
  onDelete,
}) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const open = pickerOpen || drawing;

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]">
      <Button
        variant={open ? 'default' : 'primary'}
        aria-expanded={open}
        className="self-start max-md:h-[44px]"
        onClick={() => {
          if (drawing) onStopDrawing();
          setPickerOpen(!open);
        }}
      >
        {open ? 'Свернуть' : 'Отрисовать зону'}
      </Button>

      {open && (
        <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="cad-zone-form">
          <SegmentedControl
            label="Вид зоны"
            value={kind}
            options={KIND_OPTIONS}
            onChange={onKindChange}
            layout="wrap"
          />

          {kind === 'room_apartment' && (
            <label className={LABEL}>
              № квартиры
              <ClearableInput
                label="№ квартиры"
                value={apartmentNo}
                maxLength={200}
                wrapperClassName="w-full"
                onChange={(event) => onApartmentNoChange(event.target.value)}
                onClear={() => onApartmentNoChange('')}
              />
            </label>
          )}
          {hasRoomMark(kind) && (
            <label className={LABEL}>
              Марка помещения (необязательно)
              <ClearableInput
                label="Марка помещения"
                value={roomMark}
                maxLength={200}
                placeholder="например, 3-1/6"
                wrapperClassName="w-full"
                onChange={(event) => onRoomMarkChange(event.target.value)}
                onClear={() => onRoomMarkChange('')}
              />
            </label>
          )}
          {kind === 'parking_space' && (
            <label className={LABEL}>
              Тип места
              <ParkingTypeSelect
                label="Тип машино-места"
                value={parkingType}
                onChange={onParkingTypeChange}
              />
            </label>
          )}
          {kind === 'door' && (
            <label className={LABEL}>
              Высота, мм
              <ClearableInput
                label="Высота, мм"
                value={doorHeight}
                inputMode="numeric"
                maxLength={5}
                wrapperClassName="w-full"
                onChange={(event) => onDoorHeightChange(event.target.value)}
                onClear={() => onDoorHeightChange('')}
              />
              <span>
                От {DOOR_HEIGHT_MIN_MM} до {DOOR_HEIGHT_MAX_MM} мм.
              </span>
            </label>
          )}

          {drawing ? (
            <div className="flex min-w-0 flex-col gap-[var(--s-3)]" role="status">
              <p className="text-xs">
                {kind === 'door'
                  ? 'Поставьте две точки поперёк проёма. Esc - отмена, Backspace - убрать точку.'
                  : 'Щелчком ставьте вершины. Enter, двойной щелчок или щелчок по первой вершине замыкают контур; Esc - отмена, Backspace - убрать вершину.'}
              </p>
              <Button className="self-start max-md:h-[44px]" onClick={onStopDrawing}>
                Закончить рисование
              </Button>
            </div>
          ) : (
            <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
              <Button
                variant="primary"
                disabled={drawDisabledReason !== null}
                className="self-start max-md:h-[44px]"
                onClick={onStartDrawing}
              >
                Рисовать
              </Button>
              {drawDisabledReason !== null && (
                <p className="text-xs text-muted">{drawDisabledReason}</p>
              )}
            </div>
          )}
        </div>
      )}

      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}

      {loading && (
        <div role="status" aria-label="Загрузка зон" className="flex flex-col gap-[var(--s-3)]">
          <Skeleton className="h-[20px] w-[60%]" />
          <Skeleton className="h-[16px] w-[80%]" />
        </div>
      )}
      {loadError !== null && (
        <div role="alert" className="flex flex-col gap-[var(--s-3)] text-xs text-danger">
          <span>Не удалось загрузить зоны. {loadError}</span>
          <Button compact className="self-start max-md:h-[44px]" onClick={onReload}>
            Повторить
          </Button>
        </div>
      )}
      {!loading && loadError === null && (
        <CadZoneList
          zones={zones}
          activeId={activeId}
          saving={saving}
          onActivate={onActivate}
          onRename={onRename}
          onDelete={onDelete}
          onSetParkingType={onSetParkingType}
        />
      )}
    </div>
  );
};
