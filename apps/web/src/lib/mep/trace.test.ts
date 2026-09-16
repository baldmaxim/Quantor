import { describe, expect, it } from 'vitest';

import {
  SCENARIO_COMPLETE as COMPLETE,
  SCENARIO_PARTIAL as PARTIAL,
} from '@/components/mep/__fixtures__';
import { mepAccess } from '@/lib/mep/access';
import { evidenceShapes, networkShapes } from '@/lib/mep/sheet';
import { ORIGIN_BY_PROVENANCE, buildTrace, decisionsFor, originOf } from '@/lib/mep/trace';

describe('доступ к странице', () => {
  it('до меты решения нет, выключенный флаг скрывает, включённый открывает', () => {
    expect(mepAccess(false, { mep_rd_hypothesis_v1: true })).toBe('pending');
    expect(mepAccess(true, {})).toBe('hidden');
    expect(mepAccess(true, { mep_rd_hypothesis_v1: false })).toBe('hidden');
    expect(mepAccess(true, { mep_rd_hypothesis_v1: true })).toBe('open');
  });
});

describe('происхождение сети', () => {
  it('ни одно происхождение сети не отображается как наблюдённое на П', () => {
    expect(Object.values(ORIGIN_BY_PROVENANCE)).not.toContain('observed');
  });

  it('стиль листа: evidence — наблюдено, сеть — только стилем происхождения', () => {
    expect(new Set(evidenceShapes(COMPLETE).map((s) => s.style))).toEqual(new Set(['observed']));
    const network = networkShapes(COMPLETE);
    expect(network.some((shape) => shape.style === 'observed')).toBe(false);
    expect(network.find((shape) => shape.id === 'n-j1')?.style).toBe('prior');
    expect(network.find((shape) => shape.id === 'seg-b1')?.style).toBe('rule');
    expect(network.find((shape) => shape.id === 'seg-main')?.style).toBe('evidence');
  });
});

describe('трассировка по контрактам', () => {
  const trace = buildTrace(COMPLETE);
  const lineOf = (size: number) =>
    COMPLETE.boq.lines.find(
      (line) =>
        line.rule_id === 'mep.segment_length.v0' &&
        (line.group ?? []).some((g) => g.key === 'syn.nominal_size_mm' && g.value === size),
    );

  it('строка ВОР → участок → шаг → evidence → место на листе', () => {
    const line = lineOf(50);
    expect(line?.source_ids).toEqual(['seg-main']);
    const segment = trace.network.get('seg-main');
    expect(segment?.kind).toBe('segment');
    expect(segment?.item.derivation.step_ids).toEqual(['st-3']);
    expect(trace.steps.get('st-3')?.evidence_ids).toEqual(['ev-route-1']);
    expect(trace.evidence.get('ev-route-1')?.geometry.kind).toBe('polyline');
  });

  it('evidence → сеть → ВОР в обратную сторону', () => {
    expect(trace.networkByEvidence.get('ev-route-1')).toEqual(['seg-main']);
    expect(trace.networkByEvidence.get('ev-txt-2')).toEqual(['seg-main']);
    const lines = trace.linesByNetwork.get('seg-main') ?? [];
    expect(lines).toContain(lineOf(50)?.line_id);
    expect(trace.stepsByEvidence.get('ev-route-1')).toEqual(['st-3', 'st-5']);
  });

  it('элемент без evidence не получает придуманной связи', () => {
    expect(trace.network.get('n-j1')?.item.derivation.evidence_ids ?? []).toEqual([]);
    expect([...trace.networkByEvidence.values()].flat()).not.toContain('n-j1');
  });

  it('нерешённые вопросы берутся из графа', () => {
    expect(decisionsFor(PARTIAL, 'seg-b1').map((d) => d.id)).toEqual(['ud-1']);
    expect(decisionsFor(COMPLETE, 'seg-b1')).toEqual([]);
  });

  it('происхождение параметра считается отдельно от элемента', () => {
    const material = trace.network
      .get('seg-main')
      ?.item.parameters?.find((p) => p.key === 'syn.material');
    expect(material && originOf(material.derivation)).toBe('rule');
  });
});
