'use client';

import { useMemo, type FC } from 'react';

import { CadSheetRow } from '@/components/cad/CadSheetRow';
import { takeoffAccess } from '@/components/workspace/takeoff-access';
import { Button, ErrorState, SkeletonRows } from '@/components/ui';
import { useCadJobs } from '@/lib/cad/queries';
import { useSheetCalibrationStates } from '@/lib/cad/sheet-queries';
import { latestSheetJobs } from '@/lib/cad/sheet-results';
import { sheetWorkspaceHref } from '@/lib/cad/sheets';
import { extractCode } from '@/lib/errors';
import { useFeatures, useSheets } from '@/lib/queries';

interface ICadSheetPickerProps {
  projectId: string;
  revisionId: string;
  /** Лист, открытый сейчас в рабочей области (индекс страницы): подсветка строки. */
  activePage: number | null;
  /** Открыть лист в рабочей области; результат CAD, если он есть, выберет сама область. */
  onOpenSheet: (pageIndex: number) => void;
}

/**
 * Листы ревизии (ADR-0036). Нажатие на лист открывает его в рабочей области; преобразование
 * листа в CAD запускается там же, в правой панели. Калибровка читается только у открытого
 * листа: в PDF сотни страниц, а запрос - на лист.
 */
export const CadSheetPicker: FC<ICadSheetPickerProps> = ({
  projectId,
  revisionId,
  activePage,
  onOpenSheet,
}) => {
  const sheets = useSheets(revisionId);
  const jobs = useCadJobs(projectId, revisionId);
  // Самое новое задание по каждому листу: по нему строка показывает бейдж результата.
  const results = useMemo(() => latestSheetJobs(jobs.data?.items ?? []), [jobs.data]);
  const manualEnabled = takeoffAccess(useFeatures()).enabled;
  const items = useMemo(() => sheets.data?.items ?? [], [sheets.data]);

  const openSheets = useMemo(
    () => items.filter((sheet) => sheet.page_index === activePage),
    [items, activePage],
  );
  const states = useSheetCalibrationStates(openSheets, manualEnabled);

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <p className="text-xs text-muted">Нажмите на лист, чтобы открыть его в рабочей области.</p>

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
          <ul className="flex max-h-[min(60dvh,28rem)] flex-col overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border">
            {items.map((sheet, position) => (
              <CadSheetRow
                key={sheet.id}
                sheet={sheet}
                result={results.get(sheet.page_index) ?? null}
                open={activePage === sheet.page_index}
                onOpen={() => onOpenSheet(sheet.page_index)}
                href={sheetWorkspaceHref(projectId, revisionId, position)}
                state={states.get(sheet.page_index) ?? 'unknown'}
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
    </div>
  );
};
