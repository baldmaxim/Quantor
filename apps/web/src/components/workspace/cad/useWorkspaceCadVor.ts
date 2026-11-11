'use client';

import { useMemo } from 'react';

import { useCadConstructions } from '@/lib/cad/constructions-queries';
import { useStoredBoolean } from '@/lib/cad/useStoredBoolean';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import {
  CAD_VOR_NOT_IN_VOR_VISIBLE_KEY,
  constructionVorStatus,
  notInVorIds,
  type ConstructionVorStatus,
} from '@/lib/cad/vor';
import {
  useCadVorCoverage,
  useCadVorDocuments,
  useDeleteCadVor,
  useUploadCadVor,
  vorErrorText,
} from '@/lib/cad/vor-queries';

import type { IWorkspaceCadVor } from './types';

interface IInput {
  readonly params: ICadViewParams | null;
  /** Конструкции листа прочитаны: только тогда есть что сверять. */
  readonly enabled: boolean;
  /** Момент последнего чтения конструкций: от их параметров зависит сверка. */
  readonly stamp: number;
}

export interface IWorkspaceCadVorState {
  readonly side: IWorkspaceCadVor | null;
  /** Конструкции для подсветки «не в ВОР»; `undefined` - ВОР нет или подсветка выключена. */
  readonly notInVor: ReadonlySet<string> | undefined;
}

/** ВОР Заказчика для листа: документ, сверка, загрузка и удаление. Количества ВОР с CAD не сравниваются. */
export const useWorkspaceCadVor = ({ params, enabled, stamp }: IInput): IWorkspaceCadVorState => {
  const projectId = params?.projectId ?? null;
  const [showNotInVor, setShowNotInVor] = useStoredBoolean(CAD_VOR_NOT_IN_VOR_VISIBLE_KEY, true);

  const documents = useCadVorDocuments(projectId, enabled);
  const coverageQuery = useCadVorCoverage(params, enabled, stamp);
  const upload = useUploadCadVor(projectId);
  const remove = useDeleteCadVor(projectId);

  const coverage = coverageQuery.data ?? null;
  const notInVor = useMemo(() => notInVorIds(coverage, showNotInVor), [coverage, showNotInVor]);

  if (!enabled || projectId === null) return { side: null, notInVor: undefined };

  const list = documents.data ?? [];
  const failed = upload.isError
    ? upload.error
    : remove.isError
      ? remove.error
      : documents.isError
        ? documents.error
        : coverageQuery.isError
          ? coverageQuery.error
          : null;

  return {
    notInVor,
    side: {
      projectId,
      document: list[0] ?? null,
      coverage,
      loading: documents.isPending,
      uploading: upload.isPending,
      deleting: remove.isPending,
      error: failed === null ? null : vorErrorText(failed),
      onUpload: (file) => upload.mutate({ file, replaceIds: list.map((item) => item.id) }),
      onDelete: () => {
        const current = list[0];
        if (current) remove.mutate(current.id);
      },
      showNotInVor,
      onShowNotInVorChange: setShowNotInVor,
    },
  };
};

/**
 * Статус конструкции в ВОР для карточки у курсора: «в ВОР» (строки справочно), «не в ВОР», «ВОР не
 * загружен». Читает кэш сверки и конструкций листа, сети не вызывает: данные уже загружены блоком
 * «ВОР Заказчика». `null` - данных нет.
 */
export const useConstructionVorStatus = (
  params: ICadViewParams | null,
  key: string | null,
): ConstructionVorStatus | null => {
  const read = useCadConstructions(params, false);
  const coverage = useCadVorCoverage(params, false, read.dataUpdatedAt).data;
  const construction =
    key === null ? null : read.data?.constructions.find((item) => item.id === key);
  return constructionVorStatus(coverage, construction);
};
