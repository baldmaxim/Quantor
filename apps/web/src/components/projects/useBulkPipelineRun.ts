'use client';

import type { CadPipelineRead, CadPipelineSheetRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import { sheetRows, type IPipelineAction } from '@/lib/cad/pipeline-actions';
import { nextBatchStep } from '@/lib/cad/pipeline-batch';
import { isUpdateActive } from '@/lib/cad/pipeline';
import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { cadSummaryKey } from '@/lib/cad/queue-queries';
import { cadKeys } from '@/lib/cad/queries';
import { runPipelineAction } from '@/lib/cad/runPipelineAction';

/**
 * Массовый запуск конвейера по выбранным листам: на каждое обновление конвейера ревизии для
 * каждого листа партии берётся следующий не отработанный машинный шаг (см. `nextBatchStep`) и
 * ставится на сервере; идущие шаги ждутся, решения человека - конец работы над листом.
 * Одновременно не больше {@link BULK_CAD_CONCURRENCY} запросов; отказ одного листа остальные
 * не останавливает. «Остановить» прекращает новые запуски, поставленные задания не отменяются.
 */

export const BULK_CAD_CONCURRENCY = 3;

export interface IBulkLaunchFailure {
  readonly pageIndex: number;
  readonly message: string;
}

export interface IBulkPipelineRun {
  /** Запоминает партию листов и начинает работу; пока партия идёт, повторный вызов не действует. */
  readonly start: (pageIndexes: readonly number[]) => void;
  /** Прекращает новые запуски: партия завершится, когда вернутся уже отправленные запросы. */
  readonly stop: () => void;
  readonly running: boolean;
  /** Листов в текущей (или последней) партии. */
  readonly total: number;
  /** Листов, по которым работа закончена (готов, ждёт человека или ошибка). */
  readonly finished: number;
  /** Листы с ошибкой: отказ запроса или шаг, который снова не выполнился. */
  readonly failures: readonly IBulkLaunchFailure[];
}

interface IBatch {
  readonly pages: readonly number[];
  readonly finished: Set<number>;
  /** Листы, по которым идёт запрос или обновление конвейера после него. */
  readonly inflight: Set<number>;
  /** Ключи уже запущенных в партии действий по листам. */
  readonly launched: Map<number, Set<string>>;
  /** Данные конвейера не новее этой отметки не считаются отражающими последний запуск листа. */
  readonly minUpdatedAt: Map<number, number>;
  readonly failures: IBulkLaunchFailure[];
  stopped: boolean;
}

interface IView {
  readonly running: boolean;
  readonly total: number;
  readonly finished: number;
  readonly failures: readonly IBulkLaunchFailure[];
}

const IDLE: IView = { running: false, total: 0, finished: 0, failures: [] };

export const useBulkPipelineRun = (
  projectId: string,
  revisionId: string,
  sheets: readonly CadPipelineSheetRead[],
  updatedAt: number,
  positionOf: (pageIndex: number) => number,
): IBulkPipelineRun => {
  const client = useQueryClient();
  const [view, setView] = useState<IView>(IDLE);
  const [version, setVersion] = useState(0);
  const batchRef = useRef<IBatch | null>(null);
  const lastUpdatedAt = useRef(0);
  const latest = useRef<{ sheets: readonly CadPipelineSheetRead[]; stamp: number }>({
    sheets: [],
    stamp: 0,
  });
  const positionRef = useRef(positionOf);
  // Повторный вход в `pump` после ответа сервера: сам себя из замыкания вызвать нельзя.
  const pumpRef = useRef<(current: readonly CadPipelineSheetRead[], stamp: number) => void>(
    () => undefined,
  );

  useEffect(() => {
    positionRef.current = positionOf;
  }, [positionOf]);

  const publish = useCallback((batch: IBatch) => {
    const ended =
      batch.finished.size >= batch.pages.length || (batch.stopped && batch.inflight.size === 0);
    if (ended && batchRef.current === batch) batchRef.current = null;
    setView({
      running: !ended,
      total: batch.pages.length,
      finished: batch.finished.size,
      failures: [...batch.failures],
    });
  }, []);

  const pump = useCallback(
    (current: readonly CadPipelineSheetRead[], stamp: number) => {
      const batch = batchRef.current;
      if (batch === null) return;
      lastUpdatedAt.current = stamp;

      const finish = (pageIndex: number, failure?: string) => {
        batch.finished.add(pageIndex);
        if (failure !== undefined) batch.failures.push({ pageIndex, message: failure });
      };

      const launch = (
        pageIndex: number,
        sheet: CadPipelineSheetRead,
        action: IPipelineAction,
        key: string,
      ) => {
        const keys = batch.launched.get(pageIndex) ?? new Set<string>();
        keys.add(key);
        batch.launched.set(pageIndex, keys);
        batch.minUpdatedAt.set(pageIndex, lastUpdatedAt.current);
        batch.inflight.add(pageIndex);
        void (async () => {
          try {
            await runPipelineAction({
              projectId,
              revisionId,
              action,
              convertJobId: sheet.convert?.job_id ?? null,
            });
          } catch (error) {
            finish(pageIndex, cadErrorText(error));
          }
          await Promise.all([
            client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) }),
            client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) }),
            client.invalidateQueries({ queryKey: cadSummaryKey(projectId) }),
          ]);
          batch.inflight.delete(pageIndex);
          // Самые свежие данные: из кеша запроса или те, что экран получил последними.
          const state = client.getQueryState<CadPipelineRead>(
            cadPipelineKey(projectId, revisionId),
          );
          const known = latest.current;
          if (state?.data && state.dataUpdatedAt >= known.stamp) {
            pumpRef.current(state.data.sheets, state.dataUpdatedAt);
          } else if (known.sheets.length > 0) {
            pumpRef.current(known.sheets, known.stamp);
          } else {
            publish(batch);
          }
        })();
      };

      if (!batch.stopped) {
        for (const pageIndex of batch.pages) {
          if (batch.finished.has(pageIndex) || batch.inflight.has(pageIndex)) continue;
          const since = batch.minUpdatedAt.get(pageIndex);
          if (since !== undefined && stamp <= since) continue;
          const sheet = current.find((item) => item.page_index === pageIndex);
          if (sheet === undefined) {
            finish(pageIndex, 'Лист не найден в конвейере');
            continue;
          }
          // Идёт обновление CAD листа: ждём его завершения, повторно не запускаем.
          if (isUpdateActive(sheet)) continue;
          const rows = sheetRows(projectId, revisionId, positionRef.current(pageIndex), sheet);
          const decision = nextBatchStep(rows, batch.launched.get(pageIndex) ?? new Set());
          if (decision.kind === 'done') finish(pageIndex);
          else if (decision.kind === 'failed') finish(pageIndex, decision.message);
          else if (decision.kind === 'run' && batch.inflight.size < BULK_CAD_CONCURRENCY) {
            launch(pageIndex, sheet, decision.action, decision.key);
          }
        }
      }
      publish(batch);
    },
    [client, projectId, revisionId, publish],
  );

  useEffect(() => {
    latest.current = { sheets, stamp: updatedAt };
    pumpRef.current = pump;
    pump(sheets, updatedAt);
  }, [pump, sheets, updatedAt, version]);

  // Уход с экрана прекращает новые запуски партии.
  useEffect(
    () => () => {
      if (batchRef.current) batchRef.current.stopped = true;
    },
    [],
  );

  const start = useCallback((pageIndexes: readonly number[]) => {
    if (batchRef.current !== null || pageIndexes.length === 0) return;
    batchRef.current = {
      pages: [...new Set(pageIndexes)],
      finished: new Set(),
      inflight: new Set(),
      launched: new Map(),
      minUpdatedAt: new Map(),
      failures: [],
      stopped: false,
    };
    setView({ running: true, total: batchRef.current.pages.length, finished: 0, failures: [] });
    setVersion((value) => value + 1);
  }, []);

  const stop = useCallback(() => {
    const batch = batchRef.current;
    if (batch === null) return;
    batch.stopped = true;
    publish(batch);
  }, [publish]);

  return { start, stop, ...view };
};
