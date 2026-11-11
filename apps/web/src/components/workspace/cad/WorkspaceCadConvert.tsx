'use client';

import { useMemo, useRef, useState, type FC } from 'react';

import { takeoffAccess } from '@/components/workspace/takeoff-access';
import { Button, StatusBadge } from '@/components/ui';
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
 * Компонент привязан к листу: при смене листа его нужно монтировать заново (ключ по странице).
 */
export const WorkspaceCadConvert: FC<IWorkspaceCadConvert> = ({
  projectId,
  revisionId,
  sheetId,
  pageIndex,
  onCalibrate,
  onJobCreated,
}) => {
  const manualEnabled = takeoffAccess(useFeatures()).enabled;
  const scaleToolActive = useWorkspaceStore((state) => state.tool === 'scale');
  const create = useCreateCadJob(projectId, revisionId);
  const sheets = useMemo(() => [{ id: sheetId, page_index: pageIndex }], [sheetId, pageIndex]);
  const loaded = useSheetCalibrationStates(sheets, manualEnabled);
  // Сервер ответил 409: калибровки нет, даже если клиент её не видел.
  const [serverMissing, setServerMissing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
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
    create.mutate(
      { pages: [pageIndex] },
      {
        onSuccess: (job) => onJobCreated(job.job_id, job.requested_pages ?? [pageIndex]),
        onError: (error) => {
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
      <Button
        variant="primary"
        loading={create.isPending}
        disabled={!canLaunch}
        onClick={launch}
        className="max-md:h-[44px] max-md:w-full"
      >
        Преобразовать лист в CAD
      </Button>
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
    </div>
  );
};
