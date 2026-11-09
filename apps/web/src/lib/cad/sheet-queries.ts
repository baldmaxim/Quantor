'use client';

import { listSheetCalibrations, type SheetRead } from '@quantor/api-client';
import { useQueries } from '@tanstack/react-query';

import { queryKeys, unwrap } from '@/lib/queries';

import { hasDefaultCalibration, type SheetCalibrationState } from './sheets';

/**
 * Состояние калибровки каждого листа: страница PDF (индекс с 0) -> состояние.
 *
 * Читает те же калибровки листа (ADR-0018) и под тем же ключом, что рабочая область, поэтому
 * калибровка, созданная в просмотрщике, видна здесь после возврата. Список калибровок закрыт
 * флагом `takeoff.manual`: при выключенном флаге статус прочитать нельзя - `unknown`, запросы
 * не шлются.
 */
export const useSheetCalibrationStates = (
  sheets: readonly SheetRead[],
  enabled: boolean,
): ReadonlyMap<number, SheetCalibrationState> =>
  useQueries({
    queries: sheets.map((sheet) => ({
      queryKey: queryKeys.calibrations(sheet.id),
      enabled,
      // Калибровку делают в соседней вкладке просмотрщика: при возврате статус перечитывается.
      staleTime: 0,
      refetchOnWindowFocus: true,
      queryFn: async () =>
        unwrap(await listSheetCalibrations({ throwOnError: true, path: { sheet_id: sheet.id } })),
    })),
    combine: (results) =>
      new Map(
        sheets.map((sheet, index): [number, SheetCalibrationState] => {
          const result = results[index];
          if (!enabled || result === undefined || result.isError) {
            return [sheet.page_index, 'unknown'];
          }
          if (result.data === undefined) {
            return [sheet.page_index, 'loading'];
          }
          return [sheet.page_index, hasDefaultCalibration(result.data) ? 'calibrated' : 'missing'];
        }),
      ),
  });
