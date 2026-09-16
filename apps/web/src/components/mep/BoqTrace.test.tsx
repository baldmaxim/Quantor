import type { MepScenarioRead } from '@quantor/api-client';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { buildTrace, reviewOf, selectionFor } from '@/lib/mep/trace';

import { SCENARIO_COMPLETE, SCENARIO_HYBRID, SCENARIO_PARTIAL } from './__fixtures__';
import { BoqTable } from './BoqTable';
import { MepExperiment } from './MepExperiment';

const noop = () => undefined;

const lengthLine = (scenario: MepScenarioRead, size: number) => {
  const line = scenario.boq.lines.find(
    (item) =>
      item.rule_id === 'mep.segment_length.v0' &&
      (item.group ?? []).some((g) => g.key === 'syn.nominal_size_mm' && g.value === size),
  );
  if (!line) throw new Error('нет строки');
  return line;
};

describe('разбор строки ВОР из контракта', () => {
  it('вклады источников берутся из sources, а не делятся интерфейсом', () => {
    // Подмена вклада в копии ответа видна в интерфейсе как есть: пересчёта нет.
    const tampered = structuredClone(SCENARIO_COMPLETE);
    const line = lengthLine(tampered, 32);
    const first = line.sources?.[0];
    if (!first) throw new Error('нет источника');
    first.quantity = '11.111';

    render(<BoqTable scenario={tampered} selectedLineId={line.line_id} onSelect={noop} />);
    const detail = screen.getByRole('region', { name: 'Разбор строки ВОР' });

    expect(within(detail).getByText('11.111 м')).toBeInTheDocument();
    expect(within(detail).getByText('24.495 м')).toBeInTheDocument();
  });

  it('значение группы ведёт к параметру элемента сети', () => {
    const line = lengthLine(SCENARIO_COMPLETE, 32);
    const selected: unknown[] = [];
    render(
      <BoqTable
        scenario={SCENARIO_COMPLETE}
        selectedLineId={line.line_id}
        onSelect={(s) => selected.push(s)}
      />,
    );
    const detail = screen.getByRole('region', { name: 'Разбор строки ВОР' });

    fireEvent.click(
      within(detail).getAllByRole('button', {
        name: 'seg-b1.parameters.syn.nominal_size_mm',
      })[0] as HTMLElement,
    );

    expect(selected).toEqual([{ kind: 'network', id: 'seg-b1' }]);
  });

  it('разветвление и смена параметра перечисляют всех участников', () => {
    const branch = SCENARIO_COMPLETE.boq.lines.find((l) => l.rule_id === 'mep.branch_nodes.v0');
    const change = SCENARIO_COMPLETE.boq.lines.find((l) => l.rule_id === 'mep.parameter_change.v0');
    if (!branch || !change) throw new Error('нет строк');

    const { unmount } = render(
      <BoqTable scenario={SCENARIO_COMPLETE} selectedLineId={branch.line_id} onSelect={noop} />,
    );
    const detail = screen.getByRole('region', { name: 'Разбор строки ВОР' });
    for (const id of ['seg-main', 'seg-b1', 'seg-b2']) {
      expect(within(detail).getByRole('button', { name: id })).toBeInTheDocument();
    }
    unmount();

    render(
      <BoqTable scenario={SCENARIO_COMPLETE} selectedLineId={change.line_id} onSelect={noop} />,
    );
    const compared = screen.getByRole('region', { name: 'Разбор строки ВОР' });
    expect(within(compared).getByText('syn.nominal_size_mm = 50')).toBeInTheDocument();
    expect(within(compared).getAllByText('syn.nominal_size_mm = 32')).toHaveLength(2);
  });

  it('блокеры показывают вид объекта из типизированных ссылок', () => {
    render(<BoqTable scenario={SCENARIO_PARTIAL} selectedLineId={null} onSelect={noop} />);
    const blockers = screen.getByRole('region', { name: 'Блокеры' });

    expect(within(blockers).getAllByText('segment').length).toBeGreaterThan(0);
    expect(within(blockers).getAllByRole('button', { name: 'seg-b1' }).length).toBeGreaterThan(0);
  });
});

describe('трассировка по полям контракта', () => {
  it('источники и участники строк индексируются из sources', () => {
    const trace = buildTrace(SCENARIO_COMPLETE);
    const branch = SCENARIO_COMPLETE.boq.lines.find((l) => l.rule_id === 'mep.branch_nodes.v0');

    expect(trace.linesByNetwork.get('seg-b1')).toContain(lengthLine(SCENARIO_COMPLETE, 32).line_id);
    expect(trace.linesByParticipant.get('seg-main')).toContain(branch?.line_id);
    expect(trace.linesByNetwork.get('seg-main')).not.toContain(branch?.line_id);
  });

  it('переходы есть только для видов с панелью', () => {
    expect(selectionFor({ kind: 'segment', id: 'seg-b1' })).toEqual({
      kind: 'network',
      id: 'seg-b1',
    });
    expect(selectionFor({ kind: 'evidence_element', id: 'ev-1' })).toEqual({
      kind: 'evidence',
      id: 'ev-1',
    });
    expect(selectionFor({ kind: 'sheet', id: 'sheet-p3' })).toBeNull();
  });
});

describe('evidence, проверенный человеком', () => {
  it('история проверки определяет статус элемента', () => {
    const elements = new Map(SCENARIO_HYBRID.evidence.elements.map((e) => [e.id, e]));
    const get = (id: string) => {
      const element = elements.get(id);
      if (!element) throw new Error(id);
      return element;
    };

    expect(reviewOf(get('ev-route-1'))).toBe('corrected');
    expect(reviewOf(get('ev-term-1'))).toBe('confirmed');
    expect(reviewOf(get('ev-src-1'))).toBeNull();
  });

  it('показывает предсказание модели, исправление, автора и время', () => {
    render(<MepExperiment scenario={SCENARIO_HYBRID} />);

    expect(screen.getByText(/Evidence проверен человеком/)).toBeInTheDocument();
    expect(screen.getAllByText('исправлено человеком').length).toBe(2);

    fireEvent.click(screen.getByRole('button', { name: /ev-route-1/ }));
    const table = screen.getByRole('table', { name: 'Модель и человек' });
    expect(within(table).getByText('syn.size_label=d63')).toBeInTheDocument();
    expect(within(table).getByText('syn.size_label=d50')).toBeInTheDocument();
    expect(
      screen.getByText(/2026-09-15T09:40:00Z · user-engineer-01 · correct_attributes/),
    ).toBeInTheDocument();
  });

  it('сеть, построенная по проверенному evidence, это показывает', () => {
    render(<MepExperiment scenario={SCENARIO_HYBRID} />);

    fireEvent.click(screen.getByRole('button', { name: /2 · Сеть РД/ }));
    fireEvent.click(screen.getByRole('button', { name: /n-t2/ }));

    expect(screen.getByText('evidence проверен человеком')).toBeInTheDocument();
  });
});
