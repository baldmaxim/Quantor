'use client';

import type { SheetRead } from '@quantor/api-client';
import Link from 'next/link';
import { useMemo, useRef, useState, type FC } from 'react';

import { takeoffAccess } from '@/components/workspace/takeoff-access';
import { Button, ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { pageLabel } from '@/lib/cad/format';
import { useCreateCadJob } from '@/lib/cad/queries';
import { useSheetCalibrationStates } from '@/lib/cad/sheet-queries';
import {
  CALIBRATION_UNAVAILABLE_TEXT,
  MAX_CAD_PAGES,
  calibrationPagesOf,
  canLaunchCad,
  missingCalibrationPages,
  sheetWorkspaceHref,
  toggleSheetPage,
  type SheetCalibrationState,
} from '@/lib/cad/sheets';
import { extractCode } from '@/lib/errors';
import { useFeatures, useSheets } from '@/lib/queries';

interface ICadSheetPickerProps {
  projectId: string;
  revisionId: string;
  /** Задание создано (или найдено идущее). */
  onJobCreated: (jobId: string) => void;
}

/**
 * Выбор листов ревизии для преобразования в CAD (ADR-0036).
 *
 * Лист выбирает человек; масштаб сервер берёт из калибровки листа (ADR-0018), клиент его не
 * передаёт. Лист без калибровки выбрать для запуска нельзя: ссылка ведёт в просмотрщик листа.
 */
export const CadSheetPicker: FC<ICadSheetPickerProps> = ({
  projectId,
  revisionId,
  onJobCreated,
}) => {
  const sheets = useSheets(revisionId);
  const manualEnabled = takeoffAccess(useFeatures()).enabled;
  const items = useMemo(() => sheets.data?.items ?? [], [sheets.data]);
  const create = useCreateCadJob(projectId, revisionId);

  const [selected, setSelected] = useState<readonly number[]>([]);
  // Калибровку читаем только у выбранных листов: в PDF сотни страниц, а запрос — на лист.
  const chosen = useMemo(
    () => items.filter((sheet) => selected.includes(sheet.page_index)),
    [items, selected],
  );
  const loaded = useSheetCalibrationStates(chosen, manualEnabled);
  // Страницы, на которые сервер ответил 409: калибровки нет, даже если клиент её не видел.
  const [serverMissing, setServerMissing] = useState<readonly number[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  // Синхронная защита от двойного нажатия: isPending обновляется после рендера.
  const launching = useRef(false);

  const states = useMemo(() => {
    const merged = new Map<number, SheetCalibrationState>(loaded);
    serverMissing.forEach((index) => {
      // Калибровка, появившаяся после отказа (созданная в просмотрщике), снимает блокировку.
      if (loaded.get(index) !== 'calibrated') merged.set(index, 'missing');
    });
    return merged;
  }, [loaded, serverMissing]);

  const blocked = missingCalibrationPages(selected, states);
  const canLaunch = canLaunchCad(selected, states);

  const launch = () => {
    if (launching.current || create.isPending || !canLaunch) return;
    launching.current = true;
    setProblem(null);
    create.mutate(
      { pages: selected },
      {
        onSuccess: (job) => onJobCreated(job.job_id),
        onError: (error) => {
          setServerMissing(calibrationPagesOf(error));
          setProblem(cadErrorText(error));
        },
        onSettled: () => {
          launching.current = false;
        },
      },
    );
  };

  return (
    <section className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
      <h2 className="text-sm font-medium">Листы для преобразования</h2>
      <p className="text-xs text-muted">
        Выберите листы вручную. Масштаб берётся из калибровки листа; лист без калибровки запустить
        нельзя.
      </p>

      {sheets.isPending ? (
        <SkeletonRows rows={3} />
      ) : sheets.isError ? (
        <ErrorState
          title="Не удалось прочитать листы ревизии"
          code={extractCode(sheets.error)}
          onRetry={() => void sheets.refetch()}
        />
      ) : items.length === 0 ? (
        <div className="flex flex-wrap items-center gap-[var(--s-4)]">
          <p className="text-xs text-muted">
            У ревизии пока нет листов: они появляются после обработки файла.
          </p>
          <Button
            compact
            loading={sheets.isFetching}
            onClick={() => void sheets.refetch()}
            className="max-md:h-[44px]"
          >
            Обновить
          </Button>
        </div>
      ) : (
        <>
          {!manualEnabled && (
            <p role="note" className="text-xs text-warning">
              {CALIBRATION_UNAVAILABLE_TEXT}. Статус калибровки не читается, проверку выполнит
              сервер при запуске.
            </p>
          )}
          <ul className="flex max-h-[min(60dvh,28rem)] flex-col overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border">
            {items.map((sheet, position) => (
              <SheetRow
                key={sheet.id}
                sheet={sheet}
                href={sheetWorkspaceHref(projectId, revisionId, position)}
                state={states.get(sheet.page_index) ?? 'unknown'}
                manualEnabled={manualEnabled}
                checked={selected.includes(sheet.page_index)}
                limitReached={selected.length >= MAX_CAD_PAGES}
                onToggle={() =>
                  setSelected((current) => toggleSheetPage(current, sheet.page_index))
                }
              />
            ))}
          </ul>
          {sheets.data && sheets.data.total > items.length && (
            <p className="text-xs text-muted">
              Показаны первые {items.length} листов из {sheets.data.total}.
            </p>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <Button
          variant="primary"
          loading={create.isPending}
          disabled={!canLaunch}
          onClick={launch}
          className="max-md:h-[44px]"
        >
          Запустить преобразование
        </Button>
        <span className="text-xs text-muted">
          Выбрано: {selected.length} из {MAX_CAD_PAGES}
        </span>
      </div>
      {blocked.length > 0 && (
        <p role="note" className="text-xs text-warning">
          Нет калибровки: {blocked.map((index) => pageLabel(index)).join(', ')}. Откалибруйте листы
          или снимите выбор.
        </p>
      )}
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
    </section>
  );
};

interface ISheetRowProps {
  sheet: SheetRead;
  href: string;
  state: SheetCalibrationState;
  manualEnabled: boolean;
  checked: boolean;
  limitReached: boolean;
  onToggle: () => void;
}

const SheetRow: FC<ISheetRowProps> = ({
  sheet,
  href,
  state,
  manualEnabled,
  checked,
  limitReached,
  onToggle,
}) => {
  const extraLabel =
    sheet.page_label && sheet.page_label !== String(sheet.page_index + 1) ? sheet.page_label : null;

  return (
    <li
      className={cx(
        'flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] last:border-b-0',
        checked && 'bg-accent-soft',
      )}
    >
      <label className="flex min-h-[44px] min-w-0 flex-1 cursor-pointer items-center gap-[var(--s-4)] text-sm">
        <input
          type="checkbox"
          checked={checked}
          disabled={!checked && limitReached}
          onChange={onToggle}
          className="h-[18px] w-[18px] shrink-0 accent-accent"
        />
        <span className="[overflow-wrap:anywhere]">
          {pageLabel(sheet.page_index)}
          {extraLabel && <span className="text-muted"> · {extraLabel}</span>}
        </span>
      </label>

      {state === 'calibrated' && (
        <StatusBadge tone="success" dot={false}>
          Калибровка есть
        </StatusBadge>
      )}
      {state === 'loading' && <span className="text-xs text-muted">Проверка калибровки…</span>}
      {checked && state === 'unknown' && !manualEnabled && (
        <span className="text-xs text-muted">Калибровка не проверена</span>
      )}
      {checked && state === 'unknown' && manualEnabled && (
        <span className="text-xs text-muted">Калибровка не прочитана</span>
      )}
      {state === 'missing' && (
        <>
          <StatusBadge tone="warning" dot={false}>
            Нет калибровки
          </StatusBadge>
          {manualEnabled ? (
            <Link
              href={href}
              target="_blank"
              rel="noopener"
              className="inline-flex min-h-[44px] items-center text-xs text-accent underline underline-offset-4"
            >
              Откалибровать
            </Link>
          ) : (
            <span className="text-xs text-muted">{CALIBRATION_UNAVAILABLE_TEXT}</span>
          )}
        </>
      )}
    </li>
  );
};
