'use client';

import type { CalcLegacyCatalog } from '@quantor/api-client';
import { useState } from 'react';

import { LegacyRulesTable } from '@/components/calc/LegacyRulesTable';
import { RulesTable } from '@/components/calc/RulesTable';
import { EmptyState, ErrorState, SegmentedControl, SkeletonRows } from '@/components/ui';
import { LEGACY_CATALOG_TITLES } from '@/lib/calc/rules';
import { useCalcLegacyRules, useCalcRules } from '@/lib/calc/queries';

/**
 * Экран «Расчёты → Правила»: диагностический, только чтение. Редактора правил нет —
 * черновики, утверждение и вывод из действия идут через API реестра.
 */

type Section = 'rules' | 'legacy';
type CatalogFilter = CalcLegacyCatalog | 'ALL';

const CATALOGS: readonly CalcLegacyCatalog[] = ['VK', 'K', 'OV', 'VRF', 'FIRE'];

export const CalcRules = () => {
  const [section, setSection] = useState<Section>('rules');
  const [catalog, setCatalog] = useState<CatalogFilter>('ALL');
  const rules = useCalcRules(section === 'rules');
  const legacy = useCalcLegacyRules(section === 'legacy');

  const legacyItems = (legacy.data?.items ?? []).filter(
    (item) => catalog === 'ALL' || item.catalog === catalog,
  );

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <SegmentedControl
        label="Раздел"
        value={section}
        onChange={setSection}
        options={[
          { value: 'rules', label: 'Правила Quantor' },
          { value: 'legacy', label: 'Старый портал — карантин' },
        ]}
      />

      {section === 'rules' &&
        (rules.isError ? (
          <ErrorState title="Правила не загрузились" onRetry={() => void rules.refetch()} />
        ) : !rules.data ? (
          <SkeletonRows rows={4} />
        ) : rules.data.length === 0 ? (
          <EmptyState
            compact
            title="Правил пока нет"
            description="Утверждённых правил Quantor ещё нет: реестр наполняется только правилами с подтверждённым источником."
          />
        ) : (
          <RulesTable items={rules.data} />
        ))}

      {section === 'legacy' &&
        (legacy.isError ? (
          <ErrorState title="Каталог не загрузился" onRetry={() => void legacy.refetch()} />
        ) : !legacy.data ? (
          <SkeletonRows rows={6} />
        ) : (
          <>
            <p className="max-w-[80ch] text-sm text-muted">
              {legacy.data.entry_count} правил старого портала. Все — не проверены и в расчёте не
              используются. Идея старого правила попадает в Quantor только новым черновиком с
              инженерной проверкой.
            </p>
            <SegmentedControl
              label="Система"
              value={catalog}
              onChange={setCatalog}
              options={[
                { value: 'ALL', label: 'Все' },
                ...CATALOGS.map((value) => ({ value, label: LEGACY_CATALOG_TITLES[value] })),
              ]}
            />
            <LegacyRulesTable items={legacyItems} />
          </>
        ))}
    </div>
  );
};
