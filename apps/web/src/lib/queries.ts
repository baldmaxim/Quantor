'use client';

import {
  archiveTakeoffItem,
  createMeasurement,
  createMeasurementsBatch,
  createSheetCalibration,
  createTakeoffItem,
  deleteMeasurement,
  listSheetMeasurements,
  readSheetQuantities,
  listTakeoffItems,
  listDocumentRevisions,
  listProjectDocuments,
  listProjects,
  listRevisionSheets,
  listSheetCalibrations,
  listSheetRegions,
  listTenders,
  makeCalibrationDefault,
  readJob,
  updateMeasurement,
  readMeta,
  readProject,
  readRevisionContentUrl,
  type DocumentRead,
  type MetaResponse,
  type ProjectSummary,
  type MeasurementRead,
  type ScaleCalibrationRead,
  type TakeoffItemRead,
  type TenderBriefRead,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

/**
 * Обращения к API.
 *
 * Всё серверное состояние живёт в TanStack Query и только здесь. Ключи собраны в одном
 * месте: разъехавшиеся ключи — самая частая причина того, что данные не обновляются
 * после изменения или запрашиваются дважды.
 */

export const queryKeys = {
  meta: ['meta'] as const,
  projects: (params: ProjectsParams) => ['projects', params] as const,
  project: (projectId: string) => ['project', projectId] as const,
  documents: (projectId: string) => ['project', projectId, 'documents'] as const,
  revisions: (documentId: string) => ['document', documentId, 'revisions'] as const,
  sheets: (revisionId: string) => ['revision', revisionId, 'sheets'] as const,
  regions: (sheetId: string, blockType: string | null) =>
    ['sheet', sheetId, 'regions', blockType] as const,
  job: (jobId: string) => ['job', jobId] as const,
  contentUrl: (revisionId: string) => ['revision', revisionId, 'content-url'] as const,
  tenders: (search: string) => ['tenderhub', 'tenders', search] as const,
  calibrations: (sheetId: string) => ['sheet', sheetId, 'scale-calibrations'] as const,
  takeoffItems: (projectId: string) => ['project', projectId, 'takeoff-items'] as const,
  measurements: (sheetId: string) => ['sheet', sheetId, 'measurements'] as const,
  quantities: (sheetId: string) => ['sheet', sheetId, 'quantities'] as const,
};

export interface ProjectsParams {
  readonly search: string;
  readonly sort: 'recent' | 'name';
  readonly limit: number;
  readonly offset: number;
}

/** Задание в работе опрашивается регулярно; завершённое — нет. */
const JOB_POLL_INTERVAL = 2000;

/** Достаёт данные из ответа клиента. Экспортируется: тем же способом читает сеанс. */
export const unwrap = <T>(response: { data?: T }): T => {
  if (response.data === undefined) {
    throw new Error('Пустой ответ API');
  }
  return response.data;
};

export const useMeta = (): UseQueryResult<MetaResponse> =>
  useQuery({
    queryKey: queryKeys.meta,
    queryFn: async () => unwrap(await readMeta({ throwOnError: true })),
    // Версии и флаги меняются вместе с развёртыванием, а не в ходе работы.
    staleTime: 5 * 60_000,
  });

/**
 * Флаги возможностей.
 *
 * Пока ответ не пришёл, всё считается выключенным: показать раздел, которого нет,
 * хуже, чем на мгновение не показать существующий.
 */
export const useFeatures = (): Record<string, boolean> => {
  const { data } = useMeta();
  return data?.features ?? {};
};

export const useProjects = (params: ProjectsParams) =>
  useQuery({
    queryKey: queryKeys.projects(params),
    queryFn: async () =>
      unwrap(
        await listProjects({
          throwOnError: true,
          query: {
            search: params.search || undefined,
            sort: params.sort,
            limit: params.limit,
            offset: params.offset,
          },
        }),
      ),
    // Список показывает ход импорта, поэтому обновляется, пока страница открыта.
    refetchInterval: (query) =>
      query.state.data?.items.some(isRunning) ? JOB_POLL_INTERVAL : false,
  });

export const useProject = (projectId: string) =>
  useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: async () =>
      unwrap(await readProject({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (query) => (isRunning(query.state.data) ? JOB_POLL_INTERVAL : false),
  });

export const useProjectDocuments = (projectId: string) =>
  useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: async () =>
      unwrap(
        await listProjectDocuments({
          throwOnError: true,
          path: { project_id: projectId },
          query: { limit: 200 },
        }),
      ),
  });

export const useDocumentRevisions = (documentId: string | null) =>
  useQuery({
    queryKey: queryKeys.revisions(documentId ?? ''),
    enabled: documentId !== null,
    queryFn: async () =>
      unwrap(
        await listDocumentRevisions({
          throwOnError: true,
          path: { document_id: documentId ?? '' },
          query: { limit: 50 },
        }),
      ),
  });

export const useSheets = (revisionId: string | null) =>
  useQuery({
    queryKey: queryKeys.sheets(revisionId ?? ''),
    enabled: revisionId !== null,
    queryFn: async () =>
      unwrap(
        await listRevisionSheets({
          throwOnError: true,
          path: { revision_id: revisionId ?? '' },
          query: { limit: 500 },
        }),
      ),
    // Листы неизменяемой ревизии не меняются: перезапрашивать их незачем.
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useRegions = (sheetId: string | null, blockType: string | null) =>
  useQuery({
    queryKey: queryKeys.regions(sheetId ?? '', blockType),
    enabled: sheetId !== null,
    queryFn: async () =>
      unwrap(
        await listSheetRegions({
          throwOnError: true,
          path: { sheet_id: sheetId ?? '' },
          query: { limit: 500, block_type: blockType ?? undefined },
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

/**
 * Временная ссылка на файл ревизии.
 *
 * Обновляется заранее, до истечения: просмотрщик держит документ открытым часами,
 * и протухшая ссылка посреди работы выглядит как поломка.
 */
export const useContentUrl = (revisionId: string | null) =>
  useQuery({
    queryKey: queryKeys.contentUrl(revisionId ?? ''),
    enabled: revisionId !== null,
    queryFn: async () =>
      unwrap(
        await readRevisionContentUrl({
          throwOnError: true,
          path: { revision_id: revisionId ?? '' },
        }),
      ),
    staleTime: 0,
    refetchInterval: (query) => {
      const expires = query.state.data?.expires_in;
      return expires ? Math.max(expires - 300, 60) * 1000 : false;
    },
  });

export const useJob = (jobId: string | null) =>
  useQuery({
    queryKey: queryKeys.job(jobId ?? ''),
    enabled: jobId !== null,
    queryFn: async () =>
      unwrap(await readJob({ throwOnError: true, path: { job_id: jobId ?? '' } })),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL : false;
    },
  });

const isRunning = (project: ProjectSummary | undefined): boolean => {
  const status = project?.last_job?.status;
  return status === 'queued' || status === 'running';
};

/** Документ, пригодный к открытию в рабочей области. */
export const isRenderable = (document: DocumentRead): boolean => document.document_kind === 'pdf';

/**
 * Тендеры TenderHUB, доступные ключу сервера.
 *
 * Запрос идёт в портал, а не напрямую во внешнюю систему: ключ живёт на сервере и в
 * браузер не попадает. Список приходит целиком — на той стороне страниц нет, — поэтому
 * держим его недолго: тендеры заводят и правят в течение дня.
 */
export const useTenders = (search: string, enabled: boolean): UseQueryResult<TenderBriefRead[]> =>
  useQuery({
    queryKey: queryKeys.tenders(search),
    queryFn: async () =>
      unwrap(await listTenders({ throwOnError: true, query: { search: search || undefined } })),
    enabled,
    staleTime: 60_000,
    // Список тяжёлый и внешний: повторять его при каждом открытии окна незачем.
    refetchOnWindowFocus: false,
  });

// --------------------------------------------------------------------- масштаб чертежа

/**
 * Калибровки масштаба листа.
 *
 * Их может быть несколько: план 1:100 и узел 1:20 на одном листе — обычное дело
 * (ADR-0018). Действующая помечена `is_default`.
 */
export const useScaleCalibrations = (sheetId: string | null) =>
  useQuery({
    queryKey: queryKeys.calibrations(sheetId ?? ''),
    queryFn: async () =>
      unwrap(
        await listSheetCalibrations({ throwOnError: true, path: { sheet_id: sheetId ?? '' } }),
      ),
    enabled: Boolean(sheetId),
  });

/** Действующая калибровка листа или `null`, если масштаб не задан. */
export const useDefaultCalibration = (sheetId: string | null): ScaleCalibrationRead | null => {
  const { data } = useScaleCalibrations(sheetId);
  return data?.find((item) => item.is_default) ?? null;
};

export interface CreateCalibrationInput {
  readonly sheetId: string;
  readonly pointA: readonly [number, number];
  readonly pointB: readonly [number, number];
  readonly knownDistance: string;
  readonly unit: 'mm' | 'cm' | 'm';
}

/**
 * Создаёт калибровку по двум точкам и известному размеру.
 *
 * Коэффициент не передаётся: его считает сервер из точек и канонической геометрии
 * страницы. Значение, присланное клиентом, не было бы защитимо перед заказчиком.
 */
export const useCreateCalibration = () => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: CreateCalibrationInput) =>
      unwrap(
        await createSheetCalibration({
          throwOnError: true,
          path: { sheet_id: input.sheetId },
          body: {
            point_a: [String(input.pointA[0]), String(input.pointA[1])],
            point_b: [String(input.pointB[0]), String(input.pointB[1])],
            known_distance: input.knownDistance,
            unit: input.unit,
            make_default: true,
          },
        }),
      ),
    onSuccess: (_result, input) => {
      void client.invalidateQueries({ queryKey: queryKeys.calibrations(input.sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(input.sheetId) });
    },
  });
};

/** Делает калибровку действующей. Уже посчитанные величины при этом не меняются. */
export const useMakeCalibrationDefault = (sheetId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (calibrationId: string) =>
      unwrap(
        await makeCalibrationDefault({
          throwOnError: true,
          path: { calibration_id: calibrationId },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.calibrations(sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(sheetId) });
    },
  });
};

// ------------------------------------------------------------------------- обмеры

/** Строки обмера проекта. Архивные по умолчанию не показываются. */
export const useTakeoffItems = (projectId: string | null) =>
  useQuery({
    queryKey: queryKeys.takeoffItems(projectId ?? ''),
    queryFn: async () =>
      unwrap(await listTakeoffItems({ throwOnError: true, path: { project_id: projectId ?? '' } })),
    enabled: Boolean(projectId),
  });

/** Активные измерения открытого листа. Именно листа: документ на 77 страниц не тянем. */
export const useMeasurements = (sheetId: string | null) =>
  useQuery({
    queryKey: queryKeys.measurements(sheetId ?? ''),
    queryFn: async () =>
      unwrap(
        await listSheetMeasurements({ throwOnError: true, path: { sheet_id: sheetId ?? '' } }),
      ),
    enabled: Boolean(sheetId),
  });

/**
 * Величины открытого листа: по измерению и итог по строке обмера.
 *
 * Считает сервер, а не клиент. Число, посчитанное в браузере, невозможно предъявить: его
 * нельзя ни проверить, ни воспроизвести — а величина без основания в смете не величина
 * (ADR-0008).
 *
 * Один запрос на лист: сотня обращений ради сотни меток была бы тем же N+1, только со
 * стороны клиента.
 */
export const useSheetQuantities = (sheetId: string | null) =>
  useQuery({
    queryKey: queryKeys.quantities(sheetId ?? ''),
    queryFn: async () =>
      unwrap(await readSheetQuantities({ throwOnError: true, path: { sheet_id: sheetId ?? '' } })),
    enabled: Boolean(sheetId),
  });

export const useCreateTakeoffItem = (projectId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: { name: string; geometryType: TakeoffItemRead['geometry_type'] }) =>
      unwrap(
        await createTakeoffItem({
          throwOnError: true,
          path: { project_id: projectId },
          body: { name: input.name, geometry_type: input.geometryType },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.takeoffItems(projectId) });
    },
  });
};

export const useArchiveTakeoffItem = (projectId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (itemId: string) =>
      unwrap(await archiveTakeoffItem({ throwOnError: true, path: { item_id: itemId } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.takeoffItems(projectId) });
    },
  });
};

export const useCreateMeasurement = (sheetId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      takeoffItemId: string;
      points: readonly (readonly [number, number])[];
    }) =>
      unwrap(
        await createMeasurement({
          throwOnError: true,
          path: { sheet_id: sheetId },
          body: {
            takeoff_item_id: input.takeoffItemId,
            points: input.points.map(([x, y]) => [x, y]),
          },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.measurements(sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(sheetId) });
    },
  });
};

/**
 * Пакетная постановка меток счёта.
 *
 * Счёт должен ощущаться мгновенно: метки ставят подряд, и ждать ответа сервера на каждый
 * щелчок пользователь не должен. Пакет атомарен — либо все, либо ни одной.
 */
export const useCreateMeasurementsBatch = (sheetId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      takeoffItemId: string;
      items: readonly (readonly (readonly [number, number])[])[];
    }) =>
      unwrap(
        await createMeasurementsBatch({
          throwOnError: true,
          path: { sheet_id: sheetId },
          body: {
            takeoff_item_id: input.takeoffItemId,
            items: input.items.map((shape) => shape.map(([x, y]) => [x, y])),
          },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.measurements(sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(sheetId) });
    },
  });
};

/**
 * Правка геометрии.
 *
 * Версия обязательна: без неё клиент, открывший лист десять минут назад, молча перетёр бы
 * чужую правку. Расхождение возвращается как 409 и показывается пользователю.
 */
export const useUpdateMeasurement = (sheetId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      measurementId: string;
      points: readonly (readonly [number, number])[];
      version: number;
    }) =>
      unwrap(
        await updateMeasurement({
          throwOnError: true,
          path: { measurement_id: input.measurementId },
          body: { points: input.points.map(([x, y]) => [x, y]), version: input.version },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.measurements(sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(sheetId) });
    },
  });
};

export const useDeleteMeasurement = (sheetId: string) => {
  const client = useQueryClient();

  return useMutation({
    mutationFn: async (measurementId: string) => {
      await deleteMeasurement({ throwOnError: true, path: { measurement_id: measurementId } });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.measurements(sheetId) });
      void client.invalidateQueries({ queryKey: queryKeys.quantities(sheetId) });
    },
  });
};

export type { MeasurementRead, TakeoffItemRead };
