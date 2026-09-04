'use client';

import { useCallback, useRef, useState } from 'react';

import { errorMessage } from '@/lib/errors';
import { UploadError, uploadFile } from '@/lib/upload';

/**
 * Очередь загрузки.
 *
 * Файлы отправляются по одному, а не разом: пакет весит десятки мегабайт, и параллельная
 * отправка нескольких таких только растягивает каждую. Последовательная очередь ещё и даёт
 * понятный ход выполнения вместо нескольких полос, ползущих рывками.
 */

export type UploadStage = 'ожидание' | 'загрузка' | 'готово' | 'ошибка' | 'отменено';

export interface UploadItem {
  readonly id: string;
  readonly name: string;
  readonly size: number;
  readonly stage: UploadStage;
  /** Доля отправленного; null — размер неизвестен, показываем неопределённый ход. */
  readonly fraction: number | null;
  readonly errorCode: string | null;
  readonly errorText: string | null;
  /** Такой файл уже был в проекте — создана не новая, а найдена прежняя ревизия. */
  readonly duplicate: boolean;
}

interface StartOptions {
  readonly projectId: string;
  readonly files: readonly File[];
  readonly documentId?: string;
}

export const useUploadQueue = () => {
  const [items, setItems] = useState<readonly UploadItem[]>([]);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const start = useCallback(
    async ({ projectId, files, documentId }: StartOptions): Promise<boolean> => {
      const queue: UploadItem[] = files.map((file, index) => ({
        id: `${index}-${file.name}`,
        name: file.name,
        size: file.size,
        stage: 'ожидание',
        fraction: null,
        errorCode: null,
        errorText: null,
        duplicate: false,
      }));

      setItems(queue);
      setRunning(true);
      controller.current = new AbortController();

      let allSucceeded = true;

      for (const [index, file] of files.entries()) {
        const id = queue[index]?.id;
        if (id === undefined) continue;

        patch(id, { stage: 'загрузка', fraction: 0 });

        try {
          const result = await uploadFile({
            projectId,
            file,
            ...(documentId ? { documentId } : {}),
            signal: controller.current.signal,
            onProgress: ({ fraction }) => patch(id, { fraction }),
          });
          patch(id, { stage: 'готово', fraction: 1, duplicate: result.is_duplicate });
        } catch (error) {
          allSucceeded = false;

          if (error instanceof DOMException && error.name === 'AbortError') {
            patch(id, { stage: 'отменено' });
            break;
          }

          const code = error instanceof UploadError ? error.code : 'NETWORK_ERROR';
          patch(id, {
            stage: 'ошибка',
            errorCode: code,
            errorText: errorMessage(code, error instanceof Error ? error.message : undefined),
          });
          // Остальные файлы всё равно пробуем: отказ одного не должен отменять весь набор.
        }
      }

      setRunning(false);
      controller.current = null;
      return allSucceeded;
    },
    [patch],
  );

  const cancel = useCallback(() => {
    controller.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setItems([]);
  }, []);

  return { items, running, start, cancel, reset };
};
