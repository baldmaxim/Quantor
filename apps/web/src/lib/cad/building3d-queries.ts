'use client';

import {
  listRevisionSheets,
  readCadBuilding3D,
  type CadBuilding3dRead,
} from '@quantor/api-client';
import { useQuery, type QueryClient, type UseQueryResult } from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { queryKeys, unwrap } from '@/lib/queries';

import { sheetPosition } from './workspace-url';

/**
 * Здание целиком (колонка «Здание» вида «3D»): контуры и отметки этажей всех листов проекта с
 * конструкциями. Сервер собирает модель; здесь её только читают. После правки высот листа и
 * уровней проекта ключ инвалидируется (см. `floor3d-queries`).
 */

export const building3dKeys = {
  project: (projectId: string) => ['cad-building3d', projectId] as const,
};

export const BUILDING3D_STALE_MS = 5 * 60 * 1000;

export const useCadBuilding3d = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadBuilding3dRead> =>
  useQuery({
    queryKey: building3dKeys.project(projectId),
    enabled,
    staleTime: BUILDING3D_STALE_MS,
    queryFn: async () =>
      unwrap(await readCadBuilding3D({ throwOnError: true, path: { project_id: projectId } })),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

/**
 * Позиция листа в рабочей области (с 1) для листа любой ревизии. Листы чужой ревизии подгружаются
 * в тот же кэш, что и у `useSheets`; не получилось - лист адресуется по индексу страницы
 * (позиция обычно ему равна).
 */
export const resolveSheetPosition = async (
  client: QueryClient,
  revisionId: string,
  pageIndex: number,
): Promise<number> => {
  try {
    const sheets = await client.fetchQuery({
      queryKey: queryKeys.sheets(revisionId),
      queryFn: async () =>
        unwrap(
          await listRevisionSheets({
            throwOnError: true,
            path: { revision_id: revisionId },
            query: { limit: 500 },
          }),
        ),
      staleTime: Number.POSITIVE_INFINITY,
    });
    return sheetPosition(sheets.items, pageIndex) ?? pageIndex + 1;
  } catch {
    return pageIndex + 1;
  }
};
