'use client';

import {
  readCadPreview,
  readCadView,
  type CadPreviewRead,
  type CadViewDiagnosticsRead,
} from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { cadErrorText } from './errors';

/**
 * Диагностика и предпросмотр вида CAD (QA-контур).
 *
 * Ключ содержит всё, от чего зависит ответ: проект, ревизию, задание, попытку, страницу и вид.
 * Ответ другой попытки или вида под этим ключом не принимается: при быстром переключении
 * устаревший ответ не должен оказаться на экране.
 */

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

export const useCadView = (params: ICadViewParams): UseQueryResult<CadViewDiagnosticsRead> =>
  useQuery({
    queryKey: cadViewKeys.diagnostics(params),
    queryFn: async () => {
      const data = unwrap(await readCadView({ throwOnError: true, path: path(params) }));
      if (!sameView(data, params)) throw mismatch();
      return data;
    },
    // Результат попытки неизменяем.
    staleTime: 5 * 60_000,
    retry: retryNetwork,
  });

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
    staleTime: 5 * 60_000,
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
