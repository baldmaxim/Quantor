'use client';

import type { MepScenarioRead } from '@quantor/api-client';
import { useCallback, useMemo, useState, type FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import {
  evidenceShapes,
  networkShapes,
  originalShape,
  ORIGINAL_SUFFIX,
  sheetAspect,
  type IMepShape,
  type MepLayer,
} from '@/lib/mep/sheet';
import { buildTrace, type IMepTrace, type MepSelection } from '@/lib/mep/trace';

import { BoqTable } from './BoqTable';
import { EvidencePanel } from './EvidencePanel';
import { MepSheetCanvas } from './MepSheetCanvas';
import { NetworkPanel } from './NetworkPanel';
import { LegendSwatch } from './parts';

type Step = 1 | 2 | 3;

const STEPS: readonly { readonly step: Step; readonly label: string }[] = [
  { step: 1, label: '1 · Стадия П / evidence' },
  { step: 2, label: '2 · Сеть РД (сгенерировано)' },
  { step: 3, label: '3 · Физический ВОР' },
];

const STEP_OF: Readonly<Record<MepSelection['kind'], Step>> = { evidence: 1, network: 2, line: 3 };

/** Что подсветить на листе вместе с выбранным: только связи из контрактов. */
export const relatedTo = (
  trace: IMepTrace,
  selection: MepSelection | null,
): ReadonlySet<string> => {
  if (!selection) return new Set();
  if (selection.kind === 'evidence') {
    return new Set(trace.networkByEvidence.get(selection.id) ?? []);
  }
  const networkIds =
    selection.kind === 'network'
      ? [selection.id]
      : (trace.lines.get(selection.id)?.source_ids ?? []);
  const related = new Set<string>(networkIds);
  for (const id of networkIds) {
    const entry = trace.network.get(id);
    if (!entry) continue;
    const derivations = [
      entry.item.derivation,
      ...(entry.item.parameters ?? []).map((p) => p.derivation),
    ];
    derivations.forEach((d) =>
      (d.evidence_ids ?? []).forEach((evidenceId) => related.add(evidenceId)),
    );
  }
  return related;
};

interface IMepExperimentProps {
  readonly scenario: MepScenarioRead;
}

export const MepExperiment: FC<IMepExperimentProps> = ({ scenario }) => {
  const trace = useMemo(() => buildTrace(scenario), [scenario]);
  const [step, setStep] = useState<Step>(1);
  const [selection, setSelection] = useState<MepSelection | null>(null);

  const select = useCallback((next: MepSelection) => {
    setSelection(next);
    setStep(STEP_OF[next.kind]);
  }, []);

  const evidence = useMemo(() => evidenceShapes(scenario), [scenario]);
  const network = useMemo(() => networkShapes(scenario), [scenario]);
  // Выбранный исправленный evidence показывает рядом исходное предсказание модели.
  const ghost = useMemo(
    () =>
      step === 1 && selection?.kind === 'evidence' ? originalShape(scenario, selection.id) : null,
    [step, selection, scenario],
  );
  const shapes = useMemo<readonly IMepShape[]>(
    () => [...(ghost ? [ghost] : []), ...evidence, ...(step === 1 ? [] : network)],
    [step, evidence, network, ghost],
  );
  const dimmed = useMemo<ReadonlySet<MepLayer>>(
    () => new Set(step === 1 ? [] : ['evidence']),
    [step],
  );
  const related = useMemo(() => relatedTo(trace, selection), [trace, selection]);

  const onShape = useCallback(
    (shape: IMepShape) =>
      select({
        kind: shape.layer === 'evidence' ? 'evidence' : 'network',
        id: shape.id.replace(ORIGINAL_SUFFIX, ''),
      }),
    [select],
  );

  const selectedShapeId = selection && selection.kind !== 'line' ? selection.id : null;

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <nav aria-label="Стадии эксперимента" className="flex flex-wrap gap-[var(--s-2)]">
        {STEPS.map((item) => (
          <button
            key={item.step}
            type="button"
            aria-pressed={step === item.step}
            onClick={() => setStep(item.step)}
            className={cx(
              'press rounded-[var(--radius-sm)] border px-[var(--s-4)] py-[var(--s-2)] text-sm',
              step === item.step
                ? 'border-accent bg-accent-soft text-accent'
                : 'border-border hover:bg-surface-muted',
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="grid gap-[var(--s-5)] lg:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]">
        <section aria-label="Лист" className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <div className="flex flex-wrap items-center gap-[var(--s-4)]">
            <StatusBadge tone="neutral">синтетический лист, не PDF</StatusBadge>
            <LegendSwatch style="observed">наблюдено на П</LegendSwatch>
            {step !== 1 && (
              <span className="text-xs text-muted">сеть РД — сгенерирована поверх</span>
            )}
          </div>
          <MepSheetCanvas
            shapes={shapes}
            aspect={sheetAspect(scenario)}
            dimmed={dimmed}
            selectedId={selectedShapeId}
            relatedIds={related}
            onSelect={onShape}
            label={
              step === 1 ? 'Лист стадии П с evidence' : 'Лист: evidence П и сгенерированная сеть РД'
            }
          />
        </section>

        <div className="min-w-0">
          {step === 1 && (
            <EvidencePanel
              scenario={scenario}
              trace={trace}
              selectedId={selection?.kind === 'evidence' ? selection.id : null}
              onSelect={select}
            />
          )}
          {step !== 1 && (
            <NetworkPanel
              scenario={scenario}
              trace={trace}
              selectedId={selection?.kind === 'network' ? selection.id : null}
              onSelect={select}
            />
          )}
        </div>
      </div>

      {step === 3 && (
        <BoqTable
          scenario={scenario}
          selectedLineId={selection?.kind === 'line' ? selection.id : null}
          onSelect={select}
        />
      )}
    </div>
  );
};
