'use client';

import type { CadJobRead } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { takeoffAccess } from '@/components/workspace/takeoff-access';
import { viewLabel } from '@/lib/cad/format';
import { CALIBRATION_UNAVAILABLE_TEXT, sheetWorkspaceHref } from '@/lib/cad/sheets';
import { useFeatures, useSheets } from '@/lib/queries';

/** Код отказа вида: калибровка человека расходится с размерными цепочками. */
export const CALIBRATION_MISMATCH = 'calibration_mismatch';

interface ICadCalibrationMismatchProps {
  projectId: string;
  revisionId: string;
  job: CadJobRead;
}

/**
 * Виды результата, отклонённые из-за расхождения калибровки (`failure_code`): причина движка и
 * ссылка на лист в просмотрщике, где калибровку можно проверить.
 */
export const CadCalibrationMismatch: FC<ICadCalibrationMismatchProps> = ({
  projectId,
  revisionId,
  job,
}) => {
  const sheets = useSheets(revisionId);
  const manualEnabled = takeoffAccess(useFeatures()).enabled;

  const failed = job.pages.flatMap((page) =>
    page.views
      .filter((view) => view.failure_code === CALIBRATION_MISMATCH)
      .map((view) => ({ pageIndex: page.index, view })),
  );
  if (failed.length === 0) {
    return null;
  }

  const items = sheets.data?.items ?? [];
  const positionOf = (pageIndex: number): number => {
    const found = items.findIndex((sheet) => sheet.page_index === pageIndex);
    return found >= 0 ? found : pageIndex;
  };

  return (
    <ul role="alert" className="flex flex-col gap-[var(--s-4)]">
      {failed.map(({ pageIndex, view }) => (
        <li
          key={`${pageIndex}-${view.view}`}
          className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-danger-soft bg-danger-soft px-[var(--s-5)] py-[var(--s-4)] text-xs"
        >
          <p className="text-sm font-semibold text-danger">
            {viewLabel(pageIndex, view.view)}: калибровка расходится с размерными цепочками, DXF не
            выпущен
          </p>
          {view.failure_reason && <p className="[overflow-wrap:anywhere]">{view.failure_reason}</p>}
          {manualEnabled ? (
            <Link
              href={sheetWorkspaceHref(projectId, revisionId, positionOf(pageIndex))}
              target="_blank"
              rel="noopener"
              className="inline-flex min-h-[44px] items-center self-start text-accent underline underline-offset-4"
            >
              Проверить калибровку
            </Link>
          ) : (
            <p className="text-muted">{CALIBRATION_UNAVAILABLE_TEXT}</p>
          )}
        </li>
      ))}
    </ul>
  );
};
