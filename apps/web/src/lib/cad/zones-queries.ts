'use client';

import {
  createCadZone,
  deleteCadZone,
  listCadZones,
  updateCadZone,
  type CadZoneRead,
  type CadZoneUpdate,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { invalidateFinishSheets } from './finishes-queries';
import type { ParkingType, ZoneKind } from './zones';

/**
 * Обращения к зонам листа (флаг `cad.export`, ADR-0036). Ключ содержит проект, ревизию и лист:
 * зоны прежнего листа не могут оказаться на экране нового. Площади, периметры и ширины приходят
 * с сервера и после каждой записи перечитываются списком.
 */

export const zoneKeys = {
  page: (projectId: string, revisionId: string, pageIndex: number) =>
    ['cad', projectId, revisionId, 'zones', pageIndex] as const,
  revision: (projectId: string, revisionId: string) =>
    ['cad', projectId, revisionId, 'zones'] as const,
};

export const useCadZones = (
  projectId: string,
  revisionId: string | null,
  pageIndex: number | null,
  enabled: boolean,
): UseQueryResult<CadZoneRead[]> =>
  useQuery({
    queryKey: zoneKeys.page(projectId, revisionId ?? '', pageIndex ?? -1),
    enabled: enabled && revisionId !== null && pageIndex !== null,
    queryFn: async () =>
      unwrap(
        await listCadZones({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId ?? '', page_index: pageIndex ?? 0 },
        }),
      ),
  });

export interface INewZone {
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly kind: ZoneKind;
  readonly apartmentNo: string | null;
  readonly roomMark: string | null;
  /** Название; не задано - зона без названия. */
  readonly name?: string | null;
  readonly points: readonly (readonly [number, number])[];
  readonly doorHeightMm: number | null;
  /** Тип машино-места; задан у вида `parking_space` и только у него. */
  readonly parkingType?: ParkingType | null;
}

export const useCreateCadZone = (
  projectId: string,
): UseMutationResult<CadZoneRead, unknown, INewZone> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (zone) =>
      unwrap(
        await createCadZone({
          throwOnError: true,
          path: { project_id: projectId },
          body: {
            revision_id: zone.revisionId,
            page_index: zone.pageIndex,
            kind: zone.kind,
            apartment_no: zone.apartmentNo,
            room_mark: zone.roomMark,
            ...(zone.name !== undefined ? { name: zone.name } : {}),
            points: zone.points.map(([x, y]) => [x, y] as [number, number]),
            door_height_mm: zone.doorHeightMm,
            ...(zone.parkingType != null ? { parking_type: zone.parkingType } : {}),
          },
        }),
      ),
    onSuccess: (zone) =>
      Promise.all([
        client.invalidateQueries({
          queryKey: zoneKeys.page(projectId, zone.revision_id, zone.page_index),
        }),
        // Ведомость отделки считается по зонам: правка зоны её перечитывает.
        invalidateFinishSheets(client, projectId, zone.revision_id),
      ]),
  });
};

interface IPatchZone {
  readonly id: string;
  readonly patch: CadZoneUpdate;
}

export const useUpdateCadZone = (
  projectId: string,
): UseMutationResult<CadZoneRead, unknown, IPatchZone> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }) =>
      unwrap(await updateCadZone({ throwOnError: true, path: { zone_id: id }, body: patch })),
    onSuccess: (zone) =>
      Promise.all([
        client.invalidateQueries({
          queryKey: zoneKeys.page(projectId, zone.revision_id, zone.page_index),
        }),
        // Ведомость отделки считается по зонам: правка зоны её перечитывает.
        invalidateFinishSheets(client, projectId, zone.revision_id),
      ]),
  });
};

export const useDeleteCadZone = (
  projectId: string,
  revisionId: string | null,
): UseMutationResult<unknown, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id) => deleteCadZone({ throwOnError: true, path: { zone_id: id } }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: zoneKeys.revision(projectId, revisionId ?? '') }),
        invalidateFinishSheets(client, projectId, revisionId ?? ''),
      ]),
  });
};
