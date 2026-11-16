'use client';

import {
  createSitePin,
  revokeSitePin,
  type CadSitePinCreate,
  type CadSitePinRead,
} from '@quantor/api-client';
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';

import { useHasPermission } from '@/lib/session';
import { unwrap, useFeatures } from '@/lib/queries';

import { cadEnabled } from './access';
import { building3dKeys } from './building3d-queries';

/**
 * Ручная привязка корпуса к площадке (ADR-0052, флаг `cad.export`). Запись требует то же право, что
 * загрузка документов проекта (`document.upload`): так её защищает сервер. Это удобство интерфейса,
 * граница - ответ API.
 */

export const SITE_PIN_WRITE_PERMISSION = 'document.upload';

/** Показывать ли кнопки записи привязок: флаг `cad.export` включён и право записи есть. */
export const useCanEditSitePins = (): boolean => {
  const enabled = cadEnabled(useFeatures());
  const permitted = useHasPermission(SITE_PIN_WRITE_PERMISSION);
  return enabled && permitted;
};

/** Привязка меняет сборку здания: запрос здания (с контурами и без) перечитывается. */
const useInvalidateBuilding = (projectId: string) => {
  const client = useQueryClient();
  return (): void => {
    void client.invalidateQueries({ queryKey: building3dKeys.project(projectId) });
  };
};

export const useCreateSitePin = (
  projectId: string,
): UseMutationResult<CadSitePinRead, unknown, CadSitePinCreate> => {
  const invalidate = useInvalidateBuilding(projectId);
  return useMutation({
    mutationFn: async (body) =>
      unwrap(await createSitePin({ throwOnError: true, path: { project_id: projectId }, body })),
    onSuccess: invalidate,
  });
};

export const useRevokeSitePin = (
  projectId: string,
): UseMutationResult<CadSitePinRead, unknown, string> => {
  const invalidate = useInvalidateBuilding(projectId);
  return useMutation({
    mutationFn: async (pinId) =>
      unwrap(
        await revokeSitePin({ throwOnError: true, path: { project_id: projectId, pin_id: pinId } }),
      ),
    onSuccess: invalidate,
  });
};
