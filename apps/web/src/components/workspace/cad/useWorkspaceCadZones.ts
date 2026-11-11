'use client';

import { useMemo, useState } from 'react';

import type { CadPreviewRead, CadZoneRead } from '@quantor/api-client';

import type { ICadZoneEditProps } from '@/components/cad/viewer/CadZoneEdit';
import type { ICadZoneLayers } from '@/components/cad/viewer/CadZoneLayers';
import type { ICadZoneSplitProps } from '@/components/cad/viewer/CadZoneSplit';
import { cadErrorText } from '@/lib/cad/errors';
import type { ICadFrame } from '@/lib/cad/frame';
import type { ISnapIndex } from '@/lib/cad/zone-snap';
import { canSplitZoneKind } from '@/lib/cad/zone-split';
import { presentZoneCategories } from '@/lib/cad/zone-categories';
import { readStoredNumber, writeStoredNumber } from '@/lib/cad/useStoredNumber';
import {
  DEFAULT_DOOR_HEIGHT_MM,
  DEFAULT_PARKING_TYPE,
  hasRoomMark,
  parseDoorHeight,
  zoneInputProblem,
  type ParkingType,
  type ZoneKind,
} from '@/lib/cad/zones';
import { readZoneColors, type IZonePaintData } from '@/lib/cad/zones-painter';
import {
  useCadZones,
  useCreateCadZone,
  useDeleteCadZone,
  useUpdateCadZone,
} from '@/lib/cad/zones-queries';
import { useTheme } from '@/lib/theme';
import type { Camera } from '@/lib/viewer/camera';

import type { IWorkspaceCadZones } from './types';
import { useWorkspaceCadZoneFinish } from './useWorkspaceCadZoneFinish';
import { useZoneView } from './useZoneView';
import { useWallSnapIndex } from './useWallSnapIndex';

const DOOR_HEIGHT_KEY = 'quantor.cad.zone-door-height';
const NO_ZONES: IWorkspaceCadZones['zones'] = [];

interface IInput {
  projectId: string;
  revisionId: string | null;
  pageIndex: number | null;
  /** Размер листа у отрисовщика (pt при масштабе 1); `null` - ещё не известен. */
  pageSize: { width: number; height: number } | null;
  camera: Camera;
  /** Предпросмотр и кадр показанного вида CAD: из них берутся углы и грани стен для привязки. */
  preview?: CadPreviewRead | null;
  frame?: ICadFrame | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась хотя бы раз. */
  load: boolean;
  /** Вкладка CAD открыта: зоны рисуются и рисование работает только на ней. */
  active: boolean;
  /** Идёт отметка участка замечания: она занимает холст, рисование зоны ждёт. */
  remarksCapturing: boolean;
}

export interface IWorkspaceCadZonesState {
  readonly zones: IWorkspaceCadZones;
  /** Зоны листа и выделенная для рисовальщика слоя; `null` - рисовать нечего. */
  readonly paintData: IZonePaintData | null;
  /** Блок «Зоны» панели «Слои»; `null` - на листе зон нет. */
  readonly layers: ICadZoneLayers | null;
  /** Данные слоя захвата; `null` - режим рисования выключен. */
  readonly capture: {
    camera: Camera;
    page: { width: number; height: number };
    kind: ZoneKind;
    zones: IWorkspaceCadZones['zones'];
    /** Углы и грани стен листа; `null` - стен для привязки нет. */
    walls: ISnapIndex | null;
    onComplete: (points: [number, number][]) => void;
    onExit: () => void;
  } | null;
  /** Данные режима правки контура зоны; `null` - режим выключен. */
  readonly edit: ICadZoneEditProps | null;
  /** Данные режима разреза зоны; `null` - режим выключен. */
  readonly split: ICadZoneSplitProps | null;
}

/** Режим правки формы выбранной зоны-помещения. */
interface IShapeMode {
  readonly id: string;
  readonly mode: 'edit' | 'split';
}

/**
 * Зоны текущего листа: список с сервера, настройки рисования и режим рисования.
 *
 * Площади и ширины приходят с сервера; здесь их только показывают. № квартиры и высота двери
 * запоминаются до смены (высота - и между сеансами), марка помещения после каждой зоны
 * очищается: у соседних помещений она разная. Режим рисования остаётся включённым после зоны,
 * чтобы разметить квартиру подряд; закрывает его Esc при пустом черновике или «Отмена».
 */
export const useWorkspaceCadZones = ({
  projectId,
  revisionId,
  pageIndex,
  pageSize,
  camera,
  preview = null,
  frame = null,
  load,
  active,
  remarksCapturing,
}: IInput): IWorkspaceCadZonesState => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readZoneColors();
  }, [theme]);

  const list = useCadZones(projectId, revisionId, pageIndex, load);
  const create = useCreateCadZone(projectId);
  const update = useUpdateCadZone(projectId);
  const remove = useDeleteCadZone(projectId, revisionId);
  const finish = useWorkspaceCadZoneFinish(projectId, load);

  const [kind, setKind] = useState<ZoneKind>('room_apartment');
  const [apartmentNo, setApartmentNo] = useState('');
  const [roomMark, setRoomMark] = useState('');
  const [doorHeight, setDoorHeight] = useState(() =>
    String(readStoredNumber(DOOR_HEIGHT_KEY, DEFAULT_DOOR_HEIGHT_MM)),
  );
  const [parkingType, setParkingType] = useState<ParkingType>(DEFAULT_PARKING_TYPE);
  const [drawing, setDrawing] = useState(false);
  const [shapeMode, setShapeMode] = useState<IShapeMode | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Выбор и режим принадлежат листу: на другом листе они означали бы другое место.
  const scope = revisionId !== null && pageIndex !== null ? `${revisionId}:${pageIndex}` : null;
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setDrawing(false);
    setShapeMode(null);
    setActiveId(null);
    setError(null);
  }
  if (!active && drawing) setDrawing(false);
  if (!active && shapeMode !== null) setShapeMode(null);

  const zoneList = list.data ?? NO_ZONES;
  const input = { kind, apartmentNo, doorHeight };
  const problem = zoneInputProblem(input);
  const drawDisabledReason =
    pageSize === null
      ? 'Рисование станет доступно, когда загрузится страница PDF.'
      : remarksCapturing
        ? 'Сначала закончите отметку участка в разделе «Замечания».'
        : problem;
  const drawingOn = drawing && active && pageSize !== null && !remarksCapturing && problem === null;

  // Деталь-выбор исчез из списка (удалена, другой лист) - выделения нет.
  const selected =
    activeId !== null && zoneList.some((zone) => zone.id === activeId) ? activeId : null;

  const zoneView = useZoneView();
  const paintData = useMemo<IZonePaintData | null>(
    () =>
      active && zoneList.length > 0
        ? { zones: zoneList, colors, activeId: selected, view: zoneView.view }
        : null,
    [active, zoneList, colors, selected, zoneView.view],
  );
  const layers = useMemo<ICadZoneLayers | null>(
    () =>
      zoneList.length > 0
        ? {
            categories: presentZoneCategories(zoneList),
            view: zoneView.view,
            onSetHidden: zoneView.onSetHidden,
            onColorModeChange: zoneView.onColorModeChange,
            onLabelsOnChange: zoneView.onLabelsOnChange,
            onLabelChange: zoneView.onLabelChange,
          }
        : null,
    [zoneList, zoneView],
  );

  // Правка формы: только зона-помещение, которая есть в списке; рисование ей уступает.
  const shapeZone =
    shapeMode !== null
      ? (zoneList.find(
          (zone) =>
            zone.id === shapeMode.id &&
            (shapeMode.mode === 'split' ? canSplitZoneKind(zone.kind) : zone.kind !== 'door'),
        ) ?? null)
      : null;
  const shapeOn =
    shapeMode !== null &&
    shapeZone !== null &&
    active &&
    pageSize !== null &&
    !remarksCapturing &&
    !drawingOn;
  const shapeEditDisabledReason =
    pageSize === null
      ? 'Правка станет доступна, когда загрузится страница PDF.'
      : remarksCapturing
        ? 'Сначала закончите отметку участка в разделе «Замечания».'
        : null;

  const walls = useWallSnapIndex(preview, frame, pageSize, drawingOn || shapeOn);

  const startShape = (id: string, mode: IShapeMode['mode']) => {
    setError(null);
    setDrawing(false);
    setActiveId(id);
    setShapeMode({ id, mode });
  };

  const onSaveShape = (id: string, points: [number, number][]) => {
    setError(null);
    update.mutate(
      { id, patch: { points } },
      {
        onSuccess: () => setShapeMode(null),
        onError: (failure) => setError(cadErrorText(failure)),
      },
    );
  };

  // Разрез: большая часть остаётся исходной зоне (PATCH), меньшая - новая зона того же вида.
  const onApplySplit = async (
    source: CadZoneRead,
    keep: [number, number][],
    created: [number, number][],
  ) => {
    setError(null);
    try {
      await update.mutateAsync({ id: source.id, patch: { points: keep } });
    } catch (failure) {
      setError(cadErrorText(failure));
      return;
    }
    try {
      const next = await create.mutateAsync({
        revisionId: source.revision_id,
        pageIndex: source.page_index,
        kind: source.kind,
        apartmentNo: source.apartment_no,
        roomMark: null,
        name: `${source.name ?? ''} (2)`.trim(),
        points: created,
        doorHeightMm: null,
        parkingType: source.parking_type,
      });
      setActiveId(next.id);
    } catch (failure) {
      setError(`Зона разрезана, но вторая часть не создана. ${cadErrorText(failure)}`);
    }
    setShapeMode(null);
  };

  const onComplete = (points: [number, number][]) => {
    if (revisionId === null || pageIndex === null) return;
    setError(null);
    create.mutate(
      {
        revisionId,
        pageIndex,
        kind,
        apartmentNo: kind === 'room_apartment' ? apartmentNo.trim() : null,
        roomMark: hasRoomMark(kind) && roomMark.trim() !== '' ? roomMark.trim() : null,
        points,
        doorHeightMm: kind === 'door' ? parseDoorHeight(doorHeight) : null,
        parkingType: kind === 'parking_space' ? parkingType : null,
      },
      {
        onSuccess: (created) => {
          setActiveId(created.id);
          setRoomMark('');
        },
        onError: (failure) => setError(cadErrorText(failure)),
      },
    );
  };

  const zones: IWorkspaceCadZones = {
    zones: zoneList,
    loading: list.isPending && list.fetchStatus !== 'idle',
    loadError: list.isError ? cadErrorText(list.error) : null,
    onReload: () => void list.refetch(),
    kind,
    onKindChange: (next) => {
      setKind(next);
      setError(null);
    },
    apartmentNo,
    onApartmentNoChange: setApartmentNo,
    roomMark,
    onRoomMarkChange: setRoomMark,
    doorHeight,
    onDoorHeightChange: (value) => {
      setDoorHeight(value);
      const parsed = parseDoorHeight(value);
      if (parsed !== null) writeStoredNumber(DOOR_HEIGHT_KEY, parsed);
    },
    parkingType,
    onParkingTypeChange: setParkingType,
    onSetParkingType: (id, type) => {
      setError(null);
      update.mutate(
        { id, patch: { parking_type: type } },
        { onError: (failure) => setError(cadErrorText(failure)) },
      );
    },
    onSetRoomType: (id, type) => {
      setError(null);
      update.mutate(
        { id, patch: { room_type: type } },
        { onError: (failure) => setError(cadErrorText(failure)) },
      );
    },
    finish,
    drawing: drawingOn,
    drawDisabledReason,
    onStartDrawing: () => {
      setError(null);
      setShapeMode(null);
      setDrawing(true);
    },
    onStopDrawing: () => setDrawing(false),
    activeId: selected,
    onActivate: (id) => {
      if (shapeMode !== null && id !== shapeMode.id) setShapeMode(null);
      setActiveId(id);
    },
    saving: create.isPending || update.isPending || remove.isPending,
    error,
    onRename: (id, name) => {
      setError(null);
      update.mutate(
        { id, patch: { name: name.trim() === '' ? null : name.trim() } },
        { onError: (failure) => setError(cadErrorText(failure)) },
      );
    },
    onDelete: (id) => {
      setError(null);
      remove.mutate(id, { onError: (failure) => setError(cadErrorText(failure)) });
    },
    shapeEdit: shapeOn && shapeMode !== null ? shapeMode : null,
    shapeEditDisabledReason,
    onStartEdit: (id) => startShape(id, 'edit'),
    onStartSplit: (id) => startShape(id, 'split'),
  };

  return {
    zones,
    paintData,
    layers,
    capture:
      drawingOn && pageSize !== null
        ? {
            camera,
            page: pageSize,
            kind,
            zones: zoneList,
            walls,
            onComplete,
            onExit: () => setDrawing(false),
          }
        : null,
    edit:
      shapeOn && shapeMode?.mode === 'edit' && pageSize !== null
        ? {
            camera,
            page: pageSize,
            zones: zoneList,
            zoneId: shapeMode.id,
            walls,
            saving: update.isPending,
            error,
            onSave: (points) => onSaveShape(shapeMode.id, points),
            onCancel: () => setShapeMode(null),
          }
        : null,
    split:
      shapeOn && shapeMode?.mode === 'split' && shapeZone !== null && pageSize !== null
        ? {
            camera,
            page: pageSize,
            zones: zoneList,
            zoneId: shapeMode.id,
            saving: update.isPending || create.isPending,
            error,
            onApply: ({ keep, created }) => void onApplySplit(shapeZone, keep, created),
            onCancel: () => setShapeMode(null),
          }
        : null,
  };
};
