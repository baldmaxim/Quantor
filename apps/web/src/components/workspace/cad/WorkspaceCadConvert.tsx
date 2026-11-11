'use client';

import { useMemo, useRef, useState, type FC } from 'react';

import { takeoffAccess } from '@/components/workspace/takeoff-access';
import { Button, Dialog, DialogActions, StatusBadge } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { useCreateCadJob } from '@/lib/cad/queries';
import { useSheetCalibrationStates } from '@/lib/cad/sheet-queries';
import {
  CALIBRATION_UNAVAILABLE_TEXT,
  calibrationPagesOf,
  canLaunchCad,
  type SheetCalibrationState,
} from '@/lib/cad/sheets';
import { useFeatures } from '@/lib/queries';
import { useWorkspaceStore } from '@/store/workspace';

import type { IWorkspaceCadConvert } from './types';

/**
 * Кнопка «Преобразовать лист в CAD»: задание на одну страницу открытого листа. Масштаб сервер
 * берёт из калибровки листа (ADR-0018), клиент его не передаёт. Лист без калибровки запустить
 * нельзя: рядом кнопка «Откалибровать» включает инструмент «Масштаб» на открытом листе в текущем
 * окне; пока инструмент включён, вместо кнопки показана подсказка.
 *
 * Режим `again` — для листа, уже преобразованного в CAD: вторичная кнопка «Преобразовать заново»
 * с подтверждением. Сервер идемпотентен (ревизия + версия движка + параметры): если он вернул
 * текущее задание, повтор не нужен и об этом сказано под кнопкой.
 *
 * Компонент привязан к листу: при смене листа его нужно монтировать заново (ключ по странице).
 */
export const WorkspaceCadConvert: FC<IWorkspaceCadConvert> = ({
  projectId,
  revisionId,
  sheetId,
  pageIndex,
  onCalibrate,
  onJobCreated,
  again = false,
  currentJobId = null,
}) => {
  const manualEnabled = takeoffAccess(useFeatures()).enabled;
  const scaleToolActive = useWorkspaceStore((state) => state.tool === 'scale');
  const create = useCreateCadJob(projectId, revisionId);
  const sheets = useMemo(() => [{ id: sheetId, page_index: pageIndex }], [sheetId, pageIndex]);
  const loaded = useSheetCalibrationStates(sheets, manualEnabled);
  // Сервер ответил 409: калибровки нет, даже если клиент её не видел.
  const [serverMissing, setServerMissing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // Режим «заново»: подтверждение и ответ «задание уже есть».
  const [confirming, setConfirming] = useState(false);
  const [upToDate, setUpToDate] = useState(false);
  // Синхронная защита от двойного нажатия: isPending обновляется после рендера.
  const launching = useRef(false);

  const read: SheetCalibrationState = loaded.get(pageIndex) ?? 'unknown';
  // Калибровка, появившаяся после отказа (созданная в просмотрщике), снимает блокировку.
  const state: SheetCalibrationState = serverMissing && read !== 'calibrated' ? 'missing' : read;
  const canLaunch = canLaunchCad([pageIndex], new Map([[pageIndex, state]]));

  const launch = () => {
    if (launching.current || create.isPending || !canLaunch) return;
    launching.current = true;
    setProblem(null);
    setUpToDate(false);
    create.mutate(
      { pages: [pageIndex] },
      {
        onSuccess: (job) => {
          setConfirming(false);
          // Тот же ключ идемпотентности: сервер вернул текущее задание, повтор ничего не меняет.
          if (again && job.job_id === currentJobId) {
            setUpToDate(true);
            return;
          }
          onJobCreated(job.job_id, job.requested_pages ?? [pageIndex]);
        },
        onError: (error) => {
          setConfirming(false);
          setServerMissing(calibrationPagesOf(error).includes(pageIndex));
          setProblem(cadErrorText(error));
        },
        onSettled: () => {
          launching.current = false;
        },
      },
    );
  };

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-3)]" data-testid="workspace-cad-convert">
      {again ? (
        <Button
          compact
          disabled={!canLaunch}
          onClick={() => setConfirming(true)}
          className="max-md:h-[44px] max-md:w-full"
        >
          Преобразовать заново
        </Button>
      ) : (
        <Button
          variant="primary"
          loading={create.isPending}
          disabled={!canLaunch}
          onClick={launch}
          className="max-md:h-[44px] max-md:w-full"
        >
          Преобразовать лист в CAD
        </Button>
      )}
      {upToDate && (
        <div role="status" className="flex min-w-0 flex-col items-start gap-[var(--s-2)]">
          <StatusBadge tone="accent" dot={false}>
            Уже актуально
          </StatusBadge>
          <p className="m-0 text-xs [overflow-wrap:anywhere]">
            Лист уже преобразован текущей версией движка с этой калибровкой — CAD не перезапускался. Упавший шаг повторите кнопкой «Повторить» у шага.
          </p>
        </div>
      )}
      {state === 'missing' && (
        <div className="flex flex-wrap items-center gap-x-[var(--s-4)]">
          <StatusBadge tone="warning" dot={false}>
            Нет калибровки
          </StatusBadge>
          {manualEnabled ? (
            scaleToolActive ? (
              <span role="status" className="text-xs text-muted">
                Щёлкните две точки на листе с известным расстоянием
              </span>
            ) : (
              <button
                type="button"
                onClick={onCalibrate}
                className="inline-flex min-h-[44px] items-center text-xs text-accent underline underline-offset-4"
              >
                Откалибровать
              </button>
            )
          ) : (
            <span className="text-xs text-muted">{CALIBRATION_UNAVAILABLE_TEXT}</span>
          )}
        </div>
      )}
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
      {again && (
        <Dialog
          open={confirming}
          onClose={() => setConfirming(false)}
          busy={create.isPending}
          title="Преобразовать лист заново?"
          footer={
            <DialogActions>
              <Button onClick={() => setConfirming(false)} disabled={create.isPending}>
                Отмена
              </Button>
              <Button variant="primary" loading={create.isPending} onClick={launch}>
                Преобразовать заново
              </Button>
            </DialogActions>
          }
        >
          <p className="text-sm">
            Лист будет преобразован текущей версией CAD-движка. Конструкции пересчитаются автоматически, зоны листа сохранятся. Одобрение вида и трассы нужно будет сделать заново; ручные параметры части конструкций могут сброситься.
          </p>
        </Dialog>
      )}
    </div>
  );
};
