'use client';

import {
  createCalcFact,
  createCalcSource,
  decideCalcConflict,
  listCalcConflicts,
  listCalcSources,
  reviewCalcFact,
  withdrawCalcFact,
  type CalcFactCreate,
  type CalcFactSubject,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { calcQueryKeys } from '@/lib/calc/queries';
import { unwrap } from '@/lib/queries';

/**
 * Действия человека с реестром фактов (PROMPT 01–02): ручной ввод, подтверждение и
 * отклонение утверждения, отзыв, решение конфликта источников. Каждое действие меняет
 * готовность и таблицу фактов — сбрасываются все запросы расчётов проекта.
 */

const MANUAL_TITLE = 'Ручной ввод';

export interface IManualFact {
  factType: string;
  subject: CalcFactSubject;
  value: CalcFactCreate['value'];
  note: string;
  /** Допущение вместо значения по документу — только где политика требования это разрешает. */
  alternatives?: string[];
}

const manualSource = async (projectId: string): Promise<string> => {
  const path = { project_id: projectId };
  const sources = unwrap(await listCalcSources({ throwOnError: true, path }));
  const found = sources.find(
    (item) => item.source_class === 'MANUAL' && item.title === MANUAL_TITLE,
  );
  if (found) return found.id;
  const created = unwrap(
    await createCalcSource({
      throwOnError: true,
      path,
      body: { source_class: 'MANUAL', title: MANUAL_TITLE },
    }),
  );
  return created.id;
};

const useInvalidate = (projectId: string) => {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: calcQueryKeys.project(projectId) });
};

export const useAddManualFact = (projectId: string) => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async (input: IManualFact) =>
      unwrap(
        await createCalcFact({
          throwOnError: true,
          path: { project_id: projectId },
          body: {
            source_id: await manualSource(projectId),
            fact_type: input.factType,
            subject: input.subject,
            value: input.value,
            method: input.alternatives ? 'ASSUMPTION' : 'MANUAL',
            note: input.note,
            evidence: input.alternatives
              ? [
                  {
                    kind: 'ASSUMPTION_BASIS',
                    basis: input.note,
                    alternatives: input.alternatives,
                  },
                ]
              : [],
          },
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useReviewFact = (projectId: string) => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async (input: {
      factId: string;
      status: 'CONFIRMED' | 'REJECTED';
      comment: string | null;
    }) =>
      unwrap(
        await reviewCalcFact({
          throwOnError: true,
          path: { fact_id: input.factId },
          body: { status: input.status, comment: input.comment },
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useWithdrawFact = (projectId: string) => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async (input: { factId: string; reason: string }) =>
      unwrap(
        await withdrawCalcFact({
          throwOnError: true,
          path: { fact_id: input.factId },
          body: { reason: input.reason },
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useCalcConflicts = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: [...calcQueryKeys.project(projectId), 'conflicts'] as const,
    enabled,
    queryFn: async () =>
      unwrap(await listCalcConflicts({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useDecideConflict = (projectId: string) => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async (input: { conflictId: string; chosenFactId: string; reason: string }) =>
      unwrap(
        await decideCalcConflict({
          throwOnError: true,
          path: { conflict_id: input.conflictId },
          body: { chosen_fact_id: input.chosenFactId, reason: input.reason },
        }),
      ),
    onSuccess: invalidate,
  });
};
