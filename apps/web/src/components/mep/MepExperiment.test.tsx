import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  SCENARIO_COMPLETE as COMPLETE,
  SCENARIO_PARTIAL as PARTIAL,
  SCENARIO_REFUSED as REFUSED,
} from './__fixtures__';
import { BoqTable } from './BoqTable';
import { MepExperiment } from './MepExperiment';

const noop = () => undefined;

describe('физический ВОР', () => {
  it('показывает количества сервера, review_required и предупреждения', () => {
    render(<BoqTable scenario={COMPLETE} selectedLineId={null} onSelect={noop} />);

    expect(screen.getByText('рассчитан полностью')).toBeInTheDocument();
    expect(screen.getAllByText('21.025').length).toBeGreaterThan(0);
    expect(screen.getAllByText('48.990').length).toBeGreaterThan(0);
    expect(screen.getAllByText('review_required').length).toBeGreaterThan(0);
    expect(
      within(screen.getByRole('region', { name: 'Предупреждения' })).getByText(
        'FITTING_RULES_NOT_APPROVED',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Это не ВОР/)).toBeInTheDocument();
  });

  it('частичный сценарий показывает блокеры', () => {
    render(<BoqTable scenario={PARTIAL} selectedLineId={null} onSelect={noop} />);
    const blockers = screen.getByRole('region', { name: 'Блокеры' });

    expect(screen.getByText('рассчитан частично')).toBeInTheDocument();
    expect(within(blockers).getAllByText('PARAMETER_UNRESOLVED')).toHaveLength(3);
  });

  it('отказ: строк нет, блокер целостности', () => {
    render(<BoqTable scenario={REFUSED} selectedLineId={null} onSelect={noop} />);

    expect(screen.getByText('расчёт отказан')).toBeInTheDocument();
    expect(screen.getByText('Строк нет.')).toBeInTheDocument();
    expect(screen.getByText('NETWORK_INVALID')).toBeInTheDocument();
    const graph = screen.getByRole('region', { name: 'Проверка графа' });
    expect(within(graph).getByText('CALIBRATION_FINGERPRINT_MISMATCH')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'sheet-p3' })).toBeNull();
  });
});

describe('трассировка на странице', () => {
  it('строка ВОР → участок → evidence и обратно к ВОР', () => {
    render(<MepExperiment scenario={COMPLETE} />);

    fireEvent.click(screen.getByRole('button', { name: /3 · Физический ВОР/ }));
    const row = (screen.getAllByText('21.025')[0] as HTMLElement).closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: 'seg-main' }));

    const network = screen.getByRole('list', { name: 'Элементы сети' })
      .parentElement as HTMLElement;
    expect(within(network).getByText('Участок seg-main')).toBeInTheDocument();
    expect(within(network).getByText('сгенерировано, не распознано на П')).toBeInTheDocument();
    expect(within(network).getByRole('article', { name: 'Шаг st-3' })).toBeInTheDocument();

    fireEvent.click(
      within(network).getAllByRole('button', { name: 'ev-route-1' })[0] as HTMLElement,
    );
    expect(screen.getByText('Evidence ev-route-1')).toBeInTheDocument();
    expect(screen.getAllByText('наблюдено на П').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'seg-main' }));
    const lines = screen.getByText('Строки ВОР').nextElementSibling as HTMLElement;
    fireEvent.click(within(lines).getAllByRole('button')[0] as HTMLElement);
    expect(screen.getByRole('button', { name: /3 · Физический ВОР/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('узел без evidence честно показывает, что на П его нет', () => {
    render(<MepExperiment scenario={COMPLETE} />);

    fireEvent.click(screen.getByRole('button', { name: /2 · Сеть РД/ }));
    fireEvent.click(screen.getByRole('button', { name: /n-j1/ }));

    expect(screen.getByText('нет — на листе П не показан')).toBeInTheDocument();
    expect(screen.getAllByText('сгенерировано по опыту РД').length).toBeGreaterThan(0);
    expect(screen.queryByText('наблюдено на П', { selector: '[aria-pressed] *' })).toBeNull();
  });

  it('evidence показывает режим входа и пробелы', () => {
    render(<MepExperiment scenario={PARTIAL} />);

    expect(
      within(screen.getByRole('list', { name: 'Режим входа' })).getByText('MODEL_EXTRACTED'),
    ).toBeInTheDocument();
    expect(screen.getByText('no_visible_route_to_terminals')).toBeInTheDocument();
  });
});
