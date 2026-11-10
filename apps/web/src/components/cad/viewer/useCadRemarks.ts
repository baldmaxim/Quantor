'use client';

import { useCallback, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import {
  useCadRemarksList,
  useDeleteCadRemark,
  useImportCadRemarks,
  useSaveCadRemark,
} from '@/lib/cad/queries';
import {
  MAX_REVIEWER_LENGTH,
  REVIEWER_STORAGE_KEY,
  newRemarkId,
  type BboxPt,
  type IRemark,
  type IRemarkBinding,
  type RemarkStatus,
  type RemarkType,
} from '@/lib/cad/remarks';
import type { CadRemarksFile, CadRemarksImportRead, CadRemarkWrite } from '@quantor/api-client';

/**
 * Замечания вида на сервере.
 *
 * Данные - серверный список (TanStack Query); правка - один запрос на действие, и только по
 * завершении жеста: рамку рисует и держит черновик компонент, в `add` она попадает целиком.
 * Отказ записи не теряет данные: черновик остаётся у вызывающего, ошибка - в `error`.
 * В браузере хранится только имя проверяющего (удобство, не данные замечаний).
 */

export interface IRemarkDraft {
  readonly type: RemarkType;
  readonly comment: string;
}

export interface ICadRemarks {
  /** Замечания текущей попытки и вида в порядке номеров. */
  readonly remarks: readonly IRemark[];
  /** Список ещё не получен с сервера. */
  readonly loading: boolean;
  /** Текст отказа загрузки списка; `null` - список получен. */
  readonly loadError: string | null;
  readonly reload: () => void;
  readonly reviewer: string;
  readonly setReviewer: (value: string) => void;
  /** Запись или удаление идёт. */
  readonly saving: boolean;
  /** Отказ последней записи или удаления; сбрасывается следующей успешной операцией. */
  readonly error: string | null;
  /** Новое замечание; `null` - сервер не принял (причина в `error`), черновик не терять. */
  readonly add: (bbox: BboxPt, draft: IRemarkDraft) => Promise<IRemark | null>;
  readonly update: (id: string, patch: Partial<IRemarkDraft> & { status?: RemarkStatus }) => void;
  readonly remove: (id: string) => void;
  /** Импорт файла: слияние на сервере. Отказ пробрасывается вызывающему. */
  readonly importFile: (file: CadRemarksFile) => Promise<CadRemarksImportRead>;
}

// Общее пустое значение: новый массив на каждый рендер пересоздавал бы слои холста.
const NO_REMARKS: readonly IRemark[] = [];

const readReviewer = (): string => {
  try {
    return window.localStorage.getItem(REVIEWER_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
};

const writeReviewer = (value: string): void => {
  try {
    window.localStorage.setItem(REVIEWER_STORAGE_KEY, value);
  } catch {
    // Имя - удобство: если браузер не сохранил, его просто вводят заново.
  }
};

export const useCadRemarks = (binding: IRemarkBinding, enabled = true): ICadRemarks => {
  const list = useCadRemarksList(binding, enabled);
  const { mutateAsync: saveRemark, isPending: saveBusy } = useSaveCadRemark(binding);
  const { mutateAsync: deleteRemark, isPending: deleteBusy } = useDeleteCadRemark(binding);
  const { mutateAsync: importRemarks } = useImportCadRemarks(binding);
  const [reviewer, setReviewerState] = useState(readReviewer);
  const [error, setError] = useState<string | null>(null);

  const remarks: readonly IRemark[] = list.data ?? NO_REMARKS;

  const bodyOf = useCallback(
    (source: Omit<CadRemarkWrite, 'dxf_sha256'>): CadRemarkWrite => ({
      ...source,
      dxf_sha256: binding.dxfSha256,
    }),
    [binding.dxfSha256],
  );

  const run = useCallback(async <T>(action: () => Promise<T>, what: string): Promise<T | null> => {
    setError(null);
    try {
      return await action();
    } catch (failure) {
      setError(`${what} ${cadErrorText(failure)}`);
      return null;
    }
  }, []);

  const add = useCallback<ICadRemarks['add']>(
    (bbox, draft) =>
      run(
        () =>
          saveRemark({
            id: newRemarkId(),
            body: bodyOf({
              type: draft.type,
              comment: draft.comment,
              reviewer: reviewer.trim(),
              status: 'open',
              bbox_pt: [bbox[0], bbox[1], bbox[2], bbox[3]],
            }),
          }),
        'Замечание не сохранено.',
      ),
    [run, saveRemark, bodyOf, reviewer],
  );

  const update = useCallback<ICadRemarks['update']>(
    (id, patch) => {
      const current = remarks.find((item) => item.id === id);
      if (!current) return;
      void run(
        () =>
          saveRemark({
            id,
            body: bodyOf({
              type: patch.type ?? current.type,
              comment: patch.comment ?? current.comment,
              reviewer: current.reviewer,
              status: patch.status ?? current.status,
              bbox_pt: [
                current.bbox_pt[0],
                current.bbox_pt[1],
                current.bbox_pt[2],
                current.bbox_pt[3],
              ],
            }),
          }),
        'Изменение не сохранено.',
      );
    },
    [remarks, run, saveRemark, bodyOf],
  );

  const remove = useCallback<ICadRemarks['remove']>(
    (id) => void run(() => deleteRemark(id), 'Замечание не удалено.'),
    [run, deleteRemark],
  );

  const importFile = useCallback<ICadRemarks['importFile']>(
    (file) => importRemarks(file),
    [importRemarks],
  );

  const setReviewer = useCallback((value: string) => {
    const next = value.slice(0, MAX_REVIEWER_LENGTH);
    setReviewerState(next);
    writeReviewer(next);
  }, []);

  return {
    remarks,
    loading: list.isPending,
    loadError: list.isError ? cadErrorText(list.error) : null,
    reload: () => void list.refetch(),
    reviewer,
    setReviewer,
    saving: saveBusy || deleteBusy,
    error,
    add,
    update,
    remove,
    importFile,
  };
};
