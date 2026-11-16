'use client';

import type {
  CadBuilding3dFloorRead,
  CadBuilding3dGroupRead,
  CadSitePinRead,
} from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableTextarea } from '@/components/ui/ClearableTextarea';
import { floorKey } from '@/lib/cad/building3d-geometry';
import { cadErrorText } from '@/lib/cad/errors';
import { sourceFloorsOf, targetFloorsOf } from '@/lib/cad/site-pin-floors';
import {
  buildSitePinBody,
  EMPTY_PIN_POINTS,
  formatPercent,
  isComplete,
  pinHint,
  SITE_PIN_MAX_MISMATCH,
  SITE_PIN_MIN_BASELINE_MM,
  type PinPoints,
} from '@/lib/cad/site-pin-geometry';
import { useCreateSitePin } from '@/lib/cad/site-pin-queries';

import { SitePinPlanPanel } from './SitePinPlanPanel';

interface IBuildingSitePinDialogProps {
  readonly projectId: string;
  /** Корпус, который привязывают к площадке. */
  readonly group: CadBuilding3dGroupRead;
  readonly groups: readonly CadBuilding3dGroupRead[];
  readonly floors: readonly CadBuilding3dFloorRead[];
  readonly onClose: () => void;
  /** Сервер принял привязку: ответ с поворотом, сдвигом и невязкой. */
  readonly onCreated: (pin: CadSitePinRead) => void;
}

const NOTE_MAX = 2000;

const meters = (valueMm: number): string => `${(valueMm / 1000).toFixed(2).replace('.', ',')} м`;

/**
 * Диалог «Привязать вручную» (ADR-0052): две панели плана - этаж корпуса и этаж поставленного здания,
 * на каждой по две точки; соответствие 1-1 и 2-2. Длины и расхождение под панелями - предварительная
 * подсказка с теми же порогами, что на сервере; кнопку они не блокируют. Поворот, сдвиг и невязку
 * считает сервер и возвращает в ответе.
 */
export const BuildingSitePinDialog: FC<IBuildingSitePinDialogProps> = ({
  projectId,
  group,
  groups,
  floors,
  onClose,
  onCreated,
}) => {
  const sourceFloors = useMemo(() => sourceFloorsOf(floors, group.key), [floors, group.key]);
  const target = useMemo(() => targetFloorsOf(floors, groups, group.key), [floors, groups, group.key]);
  const [sourceKey, setSourceKey] = useState(() => {
    const first = sourceFloors[0];
    return first === undefined ? '' : floorKey(first);
  });
  const [targetKey, setTargetKey] = useState(target.defaultKey ?? '');
  const [sourcePoints, setSourcePoints] = useState<PinPoints>(EMPTY_PIN_POINTS);
  const [targetPoints, setTargetPoints] = useState<PinPoints>(EMPTY_PIN_POINTS);
  const [note, setNote] = useState('');
  const create = useCreateSitePin(projectId);

  const sourceFloor = sourceFloors.find((item) => floorKey(item) === sourceKey) ?? null;
  const targetFloor = target.floors.find((item) => floorKey(item) === targetKey) ?? null;
  const body =
    sourceFloor === null || targetFloor === null
      ? null
      : buildSitePinBody(sourceFloor, targetFloor, sourcePoints, targetPoints, note);
  const hint =
    isComplete(sourcePoints) && isComplete(targetPoints) ? pinHint(sourcePoints, targetPoints) : null;

  const submit = (): void => {
    if (body === null) return;
    create.mutate(body, {
      onSuccess: (pin) => {
        onCreated(pin);
        onClose();
      },
    });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      busy={create.isPending}
      size="xl"
      title={`Привязать вручную: ${group.label}`}
      description="Укажите на плане корпуса две точки и те же две точки на плане уже поставленного здания: 1 к 1, 2 ко 2."
      footer={
        <DialogActions>
          <Button className="min-h-[44px] md:min-h-8" onClick={onClose} disabled={create.isPending}>
            Отмена
          </Button>
          <Button
            variant="primary"
            className="min-h-[44px] md:min-h-8"
            disabled={body === null || create.isPending}
            onClick={submit}
          >
            {create.isPending ? 'Привязываем…' : 'Привязать'}
          </Button>
        </DialogActions>
      }
    >
      {sourceFloors.length === 0 || target.floors.length === 0 ? (
        <p role="status" className="text-sm text-muted">
          {sourceFloors.length === 0
            ? 'У корпуса нет этажей с контурами: привязывать не по чему.'
            : 'На объекте нет поставленных зданий с контурами: привязывать не к чему.'}
        </p>
      ) : (
        <>
          <div className="grid min-w-0 gap-[var(--s-5)] lg:grid-cols-2">
            <SitePinPlanPanel
              key={`s:${sourceKey}`}
              title="Корпус"
              floors={sourceFloors}
              floorValue={sourceKey}
              onFloorChange={(key) => {
                setSourceKey(key);
                setSourcePoints(EMPTY_PIN_POINTS);
              }}
              points={sourcePoints}
              onPointsChange={setSourcePoints}
            />
            <SitePinPlanPanel
              key={`t:${targetKey}`}
              title="Площадка"
              floors={target.floors}
              floorValue={targetKey}
              onFloorChange={(key) => {
                setTargetKey(key);
                setTargetPoints(EMPTY_PIN_POINTS);
              }}
              points={targetPoints}
              onPointsChange={setTargetPoints}
            />
          </div>

          <div aria-label="Предварительная проверка" className="flex flex-col gap-[var(--s-2)] text-sm">
            {hint === null ? (
              <p className="text-muted">Поставьте по две точки на каждом плане.</p>
            ) : (
              <>
                <p>
                  Предварительно: отрезок 1-2 на корпусе {meters(hint.sourceMm)}, на площадке{' '}
                  {meters(hint.targetMm)}, расхождение {formatPercent(hint.mismatch)}. Поворот, сдвиг и невязку
                  посчитает сервер.
                </p>
                {hint.shortBaseline && (
                  <p role="alert" className="text-warning">
                    База короче {SITE_PIN_MIN_BASELINE_MM / 1000} м: угол получится неточным, сервер такую
                    привязку не примет. Возьмите точки подальше друг от друга.
                  </p>
                )}
                {hint.mismatchTooBig && (
                  <p role="alert" className="text-warning">
                    Отрезки различаются больше чем на {formatPercent(SITE_PIN_MAX_MISMATCH)}: проверьте, что точки
                    указаны одни и те же, а масштаб листов верный.
                  </p>
                )}
              </>
            )}
          </div>

          <ClearableTextarea
            label="Примечание"
            placeholder="Примечание (необязательно)"
            maxLength={NOTE_MAX}
            rows={3}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onClear={() => setNote('')}
            wrapperClassName="w-full"
          />

          {create.isError && (
            <p role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
              {cadErrorText(create.error)}
            </p>
          )}
        </>
      )}
    </Dialog>
  );
};
