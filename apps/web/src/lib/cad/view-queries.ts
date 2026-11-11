'use client';

import {
  readCadPreview,
  readCadView,
  type CadPreviewRead,
  type CadViewDiagnosticsRead,
} from '@quantor/api-client';
import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { cadErrorText } from './errors';

/**
 * Диагностика и предпросмотр вида CAD (QA-контур).
 *
 * Ключ содержит всё, от чего зависит ответ: проект, ревизию, задание, попытку, страницу и вид.
 * Ответ другой попытки или вида под этим ключом не принимается: при быстром переключении
 * устаревший ответ не должен оказаться на экране.
 *
 * Неизменяем только готовый результат попытки. Диагностика, прочитанная до готовности
 * (`preview_available !== true`, пока задание идёт), не кэшируется как свежая и перечитывается
 * при завершении задания.
 */

const READY_STALE_MS = 5 * 60_000;

/** Время свежести ответа: готовый результат (есть предпросмотр) неизменяем, остальное устаревает сразу. */
export const viewStaleTime = (data: Pick<CadViewDiagnosticsRead, 'preview_available'> | undefined): number =>
  data?.preview_available === true ? READY_STALE_MS : 0;

/** Диагностику надо перечитать: задание завершено, а в кэше ответ без предпросмотра. */
export const viewNeedsRefresh = (
  data: Pick<CadViewDiagnosticsRead, 'preview_available'> | undefined,
  jobStatus: string | null | undefined,
): boolean =>
  data !== undefined &&
  data.preview_available !== true &&
  jobStatus !== undefined &&
  jobStatus !== null &&
  jobStatus !== 'queued' &&
  jobStatus !== 'running';

export interface ICadViewParams {
  readonly projectId: string;
  readonly revisionId: string;
  readonly jobId: string;
  /** Попытка, чей результат показываем (`CadJobRead.result_attempt`). */
  readonly attempt: number;
  readonly pageIndex: number;
  readonly view: number;
}

/** Код отказа, когда ответ относится не к тому виду, что запрошен. */
export const CAD_VIEW_MISMATCH = 'CAD_VIEW_MISMATCH';

const keyOf = (kind: 'diagnostics' | 'preview', params: ICadViewParams) =>
  [
    'cad-view',
    kind,
    params.projectId,
    params.revisionId,
    params.jobId,
    params.attempt,
    params.pageIndex,
    params.view,
  ] as const;

export const cadViewKeys = {
  diagnostics: (params: ICadViewParams) => keyOf('diagnostics', params),
  preview: (params: ICadViewParams) => keyOf('preview', params),
};

const mismatch = (): Error & { detail: { code: string } } =>
  Object.assign(new Error('Ответ относится к другому виду'), {
    detail: { code: CAD_VIEW_MISMATCH },
  });

const sameView = (
  data: { job_id: string; attempt: number; page_index: number; view: number },
  params: ICadViewParams,
): boolean =>
  data.job_id === params.jobId &&
  data.attempt === params.attempt &&
  data.page_index === params.pageIndex &&
  data.view === params.view;

const path = (params: ICadViewParams) => ({
  project_id: params.projectId,
  revision_id: params.revisionId,
  job_id: params.jobId,
  page_index: params.pageIndex,
  view: params.view,
});

/** Повтор только при обрыве связи: 404/409/500 от повторов не исчезнут. */
const retryNetwork = (count: number, error: Error): boolean =>
  extractCode(error) === 'NETWORK_ERROR' && count < 2;

/**
 * `jobStatus` - статус задания, чей вид читается: при переходе в терминальный статус диагностика
 * без предпросмотра (и превью) перечитывается один раз на статус попытки.
 */
export const useCadView = (
  params: ICadViewParams,
  enabled = true,
  jobStatus?: string | null,
): UseQueryResult<CadViewDiagnosticsRead> => {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: cadViewKeys.diagnostics(params),
    enabled,
    queryFn: async () => {
      const data = unwrap(await readCadView({ throwOnError: true, path: path(params) }));
      if (!sameView(data, params)) throw mismatch();
      return data;
    },
    staleTime: (q) => viewStaleTime(q.state.data),
    retry: retryNetwork,
  });

  const refreshed = useRef<string | null>(null);
  const needsRefresh = enabled && viewNeedsRefresh(query.data, jobStatus);
  const refreshKey = `${params.jobId}:${params.attempt}:${params.pageIndex}:${params.view}:${jobStatus ?? ''}`;
  useEffect(() => {
    if (!needsRefresh || refreshed.current === refreshKey) return;
    refreshed.current = refreshKey;
    void queryClient.invalidateQueries({ queryKey: cadViewKeys.diagnostics(params) });
    void queryClient.invalidateQueries({ queryKey: cadViewKeys.preview(params) });
  }, [needsRefresh, refreshKey, queryClient, params]);

  return query;
};

export const useCadPreview = (
  params: ICadViewParams,
  enabled: boolean,
): UseQueryResult<CadPreviewRead> =>
  useQuery({
    queryKey: cadViewKeys.preview(params),
    enabled,
    queryFn: async () => {
      const data = unwrap(await readCadPreview({ throwOnError: true, path: path(params) }));
      if (!sameView(data, params)) throw mismatch();
      return data;
    },
    staleTime: READY_STALE_MS,
    retry: retryNetwork,
  });

const LOCAL_MESSAGES: Readonly<Record<string, string>> = {
  CAD_RESULT_NOT_READY: 'Результат попытки ещё не готов',
  [CAD_VIEW_MISMATCH]: 'Ответ сервера относится к другому виду. Выберите вид ещё раз.',
};

/** Текст отказа для экрана: код -> подпись, иначе сообщение сервера. */
export const cadViewErrorText = (error: unknown): { code: string; text: string } => {
  const code = extractCode(error);
  return { code, text: LOCAL_MESSAGES[code] ?? cadErrorText(error) };
};
