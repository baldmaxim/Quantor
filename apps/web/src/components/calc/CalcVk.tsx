'use client';

import type { CalcPassportSummaryRead, CalcScenario } from '@quantor/api-client';
import { useId, useMemo, useState } from 'react';

import { VkCalculation } from '@/components/calc/vk/VkCalculation';
import { VkInputs } from '@/components/calc/vk/VkInputs';
import { VkAssumptions, VkUnresolved } from '@/components/calc/vk/VkIssues';
import { VkOverview } from '@/components/calc/vk/VkOverview';
import { VkStructureTab } from '@/components/calc/vk/VkStructureTab';
import { VkVolumes } from '@/components/calc/vk/VkVolumes';
import {
  Button,
  EmptyState,
  ErrorState,
  SegmentedControl,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import { SCENARIO_TITLES } from '@/lib/calc/runs';
import { PASSPORT_STATUS, VK_TABS, type VkTab } from '@/lib/calc/vk';
import {
  useCalculateVk,
  useVkAssumptions,
  useVkPassport,
  useVkPassports,
  useVkReadiness,
  useVkVolumes,
} from '@/lib/calc/vk-queries';
import { formatWhen } from '@/lib/format';
import { useHasPermission } from '@/lib/session';

/**
 * «Расчёты → ВК» (ADR-0030, PROMPT 06): комплект В1, Т3, Т4, К1 стадии П. Quantor сам собирает
 * найденные данные; человек видит только недостающее. Сверки с ВОР здесь нет.
 */

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';
const SYSTEMS = ['В1', 'Т3', 'Т4', 'К1'] as const;
const SCENARIOS: readonly CalcScenario[] = ['MINIMUM', 'EXPECTED', 'TENDER_SAFE'];

const latestBatch = (
  passports: CalcPassportSummaryRead[],
  building: string,
  section: string,
): CalcPassportSummaryRead[] => {
  const scoped = passports.filter(
    (item) => item.scope.building === building && (item.scope.section ?? '') === section,
  );
  const batch = scoped[0]?.batch_id;
  return scoped.filter((item) => item.batch_id === batch);
};

export const CalcVk = ({ projectId }: { projectId: string }) => {
  const buildingId = useId();
  const sectionId = useId();
  const [building, setBuilding] = useState('1');
  const [section, setSection] = useState('');
  const [system, setSystem] = useState<string>('В1');
  const [tab, setTab] = useState<VkTab>('overview');
  const [scenario, setScenario] = useState<CalcScenario>('EXPECTED');
  const canCalculate = useHasPermission('calc.edit');
  const passports = useVkPassports(projectId);
  const readiness = useVkReadiness(projectId, building.trim(), section.trim());
  const calculate = useCalculateVk(projectId);
  const batch = useMemo(
    () => latestBatch(passports.data ?? [], building.trim(), section.trim()),
    [passports.data, building, section],
  );
  const selected = batch.find((item) => item.system_code === system) ?? null;
  const passport = useVkPassport(selected?.id ?? null);
  const volumes = useVkVolumes(tab === 'volumes' ? (selected?.id ?? null) : null, scenario);
  const assumptions = useVkAssumptions(tab === 'assumptions' ? (selected?.id ?? null) : null);

  if (passports.isError) {
    return <ErrorState title="Паспорта не загрузились" onRetry={() => void passports.refetch()} />;
  }
  if (!passports.data) return <SkeletonRows rows={4} />;

  const open = (code: string) => {
    setSystem(code);
    setTab('volumes');
  };
  const systemReadiness = readiness.data?.systems.find((item) => item.system_code === system);

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <form
        className="flex flex-wrap items-end gap-[var(--s-4)]"
        onSubmit={(event) => {
          event.preventDefault();
          calculate.mutate({
            building: building.trim(),
            ...(section.trim() ? { section: section.trim() } : {}),
          });
        }}
      >
        <label htmlFor={buildingId} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">Корпус</span>
          <input
            id={buildingId}
            value={building}
            maxLength={64}
            onChange={(event) => setBuilding(event.target.value)}
            className={FIELD}
          />
        </label>
        <label htmlFor={sectionId} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">Секция (необязательно)</span>
          <input
            id={sectionId}
            value={section}
            maxLength={64}
            onChange={(event) => setSection(event.target.value)}
            className={FIELD}
          />
        </label>
        {canCalculate && (
          <Button type="submit" disabled={calculate.isPending || building.trim().length === 0}>
            {calculate.isPending ? 'Считаем…' : 'Рассчитать ВК'}
          </Button>
        )}
        {calculate.isError && (
          <p className="basis-full text-sm text-danger">Расчёт не выполнен: сервер отказал.</p>
        )}
      </form>

      <SegmentedControl
        label="Разделы паспорта"
        layout="wrap"
        value={tab}
        onChange={setTab}
        options={VK_TABS.map((item) => ({ value: item.value, label: item.label }))}
      />

      {tab === 'overview' ? (
        <VkOverview passports={batch} readiness={readiness.data} onOpen={open} />
      ) : (
        <div className="flex flex-col gap-[var(--s-4)]">
          <div className="flex flex-wrap items-center gap-[var(--s-4)]">
            <SegmentedControl
              label="Система"
              value={system}
              onChange={setSystem}
              options={SYSTEMS.map((code) => ({ value: code, label: code }))}
            />
            {(tab === 'volumes' || tab === 'structure') && (
              <SegmentedControl
                label="Сценарий"
                value={scenario}
                onChange={setScenario}
                options={SCENARIOS.map((item) => ({ value: item, label: SCENARIO_TITLES[item] }))}
              />
            )}
            {selected && (
              <>
                <StatusBadge tone={PASSPORT_STATUS[selected.status].tone}>
                  {PASSPORT_STATUS[selected.status].label}
                </StatusBadge>
                <span className="text-xs text-muted">{formatWhen(selected.created_at)}</span>
              </>
            )}
          </div>
          {tab === 'inputs' ? (
            <VkInputs projectId={projectId} system={systemReadiness} passport={passport.data} />
          ) : !selected ? (
            <EmptyState compact title={`Паспорта ${system} для этого корпуса ещё нет`} />
          ) : passport.isError ? (
            <ErrorState title="Паспорт не загрузился" onRetry={() => void passport.refetch()} />
          ) : !passport.data ? (
            <SkeletonRows rows={4} />
          ) : tab === 'calculation' ? (
            <VkCalculation projectId={projectId} passport={passport.data} />
          ) : tab === 'structure' ? (
            <VkStructureTab passport={passport.data} scenario={scenario} />
          ) : tab === 'volumes' ? (
            <VkVolumes
              rows={volumes.data}
              isError={volumes.isError}
              onRetry={() => void volumes.refetch()}
            />
          ) : tab === 'assumptions' ? (
            <VkAssumptions
              passport={passport.data}
              records={assumptions.data}
              isError={assumptions.isError}
              onRetry={() => void assumptions.refetch()}
            />
          ) : (
            <VkUnresolved body={passport.data.body} />
          )}
        </div>
      )}
    </div>
  );
};
