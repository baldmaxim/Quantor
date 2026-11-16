'use client';

import type { CadBuilding3dServiceSheetRead, CadBuilding3dWarningRead } from '@quantor/api-client';
import type { FC } from 'react';

interface IBuildingViewerNotesProps {
  readonly warnings: readonly CadBuilding3dWarningRead[];
  readonly serviceSheets: readonly CadBuilding3dServiceSheetRead[];
}

const LIST = 'flex flex-col gap-[var(--s-2)] px-[var(--s-4)] pb-[var(--s-3)] text-xs text-muted';

/**
 * Замечания сборки здания: чего в 3D нет и почему (планы без CAD, листы без высот, не поставленные
 * корпуса) и служебные листы - разрезы и дубли планов, не вошедшие в стопку этажей. Свёрнуто по умолчанию.
 */
export const BuildingViewerNotes: FC<IBuildingViewerNotesProps> = ({ warnings, serviceSheets }) => {
  if (warnings.length === 0 && serviceSheets.length === 0) return null;
  return (
    <details>
      <summary className="flex min-h-[44px] cursor-pointer items-center px-[var(--s-4)] text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        Замечания сборки: {warnings.length}
        {serviceSheets.length > 0 ? `, служебных листов: ${serviceSheets.length}` : ''}
      </summary>
      {warnings.length > 0 && (
        <ul aria-label="Замечания сборки" className={LIST}>
          {warnings.map((warning, index) => (
            <li key={`${warning.code}:${index}`} className="[overflow-wrap:anywhere]">
              {warning.message}
            </li>
          ))}
        </ul>
      )}
      {serviceSheets.length > 0 && (
        <>
          <h3 className="px-[var(--s-4)] pb-[var(--s-2)] text-xs font-medium text-muted">
            Служебные листы (в здание не входят)
          </h3>
          <ul aria-label="Служебные листы" className={LIST}>
            {serviceSheets.map((sheet) => (
              <li
                key={`${sheet.job_id}:${sheet.page_index}:${sheet.view}`}
                className="[overflow-wrap:anywhere]"
              >
                {sheet.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
};
