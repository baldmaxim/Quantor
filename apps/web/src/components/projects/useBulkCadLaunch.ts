'use client';

import { createCadJob } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { cadKeys } from '@/lib/cad/queries';
import { unwrap } from '@/lib/queries';

/**
 * Массовый запуск преобразования листов в CAD из панели «Обработка»: одно задание на лист
 * (`pages: [page_index]`, `auto_scale: true`), не больше {@link BULK_CAD_CONCURRENCY} запросов
 * одновременно. Отказ одного листа остальные не останавливает. После очереди конвейер ревизии
 * перечитывается: его опрос подхватит поставленные задания.
 */

export const BULK_CAD_CONCURRENCY = 3;

export interface IBulkLaunchFailure {
  readonly pageIndex: number;
  readonly message: string;
}

export interface IBulkCadLaunch {
  /** Ставит задания по листам; завершается, когда очередь разобрана. */
  readonly launch: (pageIndexes: readonly number[]) => Promise<void>;
  readonly running: boolean;
  /** Листов в текущей (или последней) очереди. */
  readonly total: number;
  /** Сколько заданий принято сервером. */
  readonly placed: number;
  /** Листы, которые поставить не удалось. */
  readonly failures: readonly IBulkLaunchFailure[];
}

export const useBulkCadLaunch = (projectId: string, revisionId: string): IBulkCadLaunch => {
  const client = useQueryClient();
  const [running, setRunning] = useState(false);
  const [total, setTotal] = useState(0);
  const [placed, setPlaced] = useState(0);
  const [failures, setFailures] = useState<readonly IBulkLaunchFailure[]>([]);
  // Синхронная защита от двойного запуска: `running` обновляется после рендера.
  const busy = useRef(false);

  const launch = useCallback(
    async (pageIndexes: readonly number[]): Promise<void> => {
      if (busy.current || pageIndexes.length === 0) return;
      busy.current = true;
      setRunning(true);
      setTotal(pageIndexes.length);
      setPlaced(0);
      setFailures([]);

      let cursor = 0;
      const worker = async (): Promise<void> => {
        while (cursor < pageIndexes.length) {
          const pageIndex = pageIndexes[cursor] as number;
          cursor += 1;
          try {
            unwrap(
              await createCadJob({
                throwOnError: true,
                path: { project_id: projectId, revision_id: revisionId },
                body: { pages: [pageIndex], finishes: false, schedules: false, auto_scale: true },
              }),
            );
            setPlaced((value) => value + 1);
          } catch (error) {
            const failure = { pageIndex, message: cadErrorText(error) };
            setFailures((previous) => [...previous, failure]);
          }
        }
      };

      try {
        const size = Math.min(BULK_CAD_CONCURRENCY, pageIndexes.length);
        await Promise.all(Array.from({ length: size }, worker));
      } finally {
        busy.current = false;
        setRunning(false);
        void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
        void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
      }
    },
    [client, projectId, revisionId],
  );

  return { launch, running, total, placed, failures };
};
