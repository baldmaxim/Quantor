'use client';

import {
  approveCalcRuleVersion,
  getCalcRule,
  listCalcVkCalculators,
  rejectCalcRuleVersion,
  saveCalcVkRuleVersion,
  type CalcVkRuleVersionCreate,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { calcQueryKeys } from '@/lib/calc/queries';
import { uniqueNeeds } from '@/lib/calc/rule-needs';
import { unwrap } from '@/lib/queries';

/**
 * Запросы раздела «Решения инженера ВК». Правила — общие для пространства, не для проекта:
 * после решения сбрасываются список правил и карточки правил; готовность ВК перечитается при
 * открытии экрана расчёта.
 */

const RULE_PREFIX = ['calc', 'rule'] as const;

export const ruleNeedKeys = {
  needs: ['calc', 'vk', 'calculators'] as const,
  rule: (ruleKey: string) => [...RULE_PREFIX, ruleKey] as const,
};

/** Заявки калькуляторов — код развёртывания: в рамках сессии не меняются. */
export const useVkRuleNeeds = (enabled: boolean) =>
  useQuery({
    queryKey: ruleNeedKeys.needs,
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () => unwrap(await listCalcVkCalculators({ throwOnError: true })),
    select: uniqueNeeds,
  });

export const useCalcRuleDetail = (ruleKey: string | null) =>
  useQuery({
    queryKey: ruleNeedKeys.rule(ruleKey ?? ''),
    enabled: ruleKey !== null,
    queryFn: async () =>
      unwrap(await getCalcRule({ throwOnError: true, path: { rule_key: ruleKey ?? '' } })),
  });

const useInvalidateRules = () => {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: calcQueryKeys.rules }),
      queryClient.invalidateQueries({ queryKey: RULE_PREFIX }),
    ]);
};

export const useSaveRuleDecision = () => {
  const invalidate = useInvalidateRules();
  return useMutation({
    mutationFn: async ({ ruleKey, body }: { ruleKey: string; body: CalcVkRuleVersionCreate }) =>
      unwrap(
        await saveCalcVkRuleVersion({ throwOnError: true, path: { rule_key: ruleKey }, body }),
      ),
    onSuccess: invalidate,
  });
};

interface IReview {
  ruleKey: string;
  version: number;
  comment: string;
}

export const useApproveRule = () => {
  const invalidate = useInvalidateRules();
  return useMutation({
    mutationFn: async ({ ruleKey, version, comment }: IReview) =>
      unwrap(
        await approveCalcRuleVersion({
          throwOnError: true,
          path: { rule_key: ruleKey, version },
          body: { comment, legacy_review: [] },
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useRejectRule = () => {
  const invalidate = useInvalidateRules();
  return useMutation({
    mutationFn: async ({ ruleKey, version, comment }: IReview) =>
      unwrap(
        await rejectCalcRuleVersion({
          throwOnError: true,
          path: { rule_key: ruleKey, version },
          body: { comment },
        }),
      ),
    onSuccess: invalidate,
  });
};
