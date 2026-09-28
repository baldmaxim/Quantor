import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { resultTrace, runSummary } from './__fixtures__/runs';

import { RunTrace } from './RunTrace';
import { RunsTable } from './RunsTable';

/**
 * Экран запусков: итог и причина блокировки — ответ сервера; объяснение — дерево сервера.
 */

describe('запуски расчёта', () => {
  it('показывает калькулятор, сценарий, статус и число результатов', () => {
    const onSelect = vi.fn();
    render(<RunsTable runs={[runSummary()]} selected={null} onSelect={onSelect} />);
    expect(screen.getByText('test.vertical_length@1')).toBeInTheDocument();
    expect(screen.getByText('Ожидаемый')).toBeInTheDocument();
    expect(screen.getByText('рассчитано')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(onSelect).toHaveBeenCalledWith('44444444-4444-4444-8444-444444444444');
  });

  it('заблокированный запуск показывает причину, а не ноль', () => {
    const blocked = runSummary({
      status: 'BLOCKED',
      results_count: 0,
      blocking: '«floor.height@building=1|floor=2..24»: в реестре фактов значения нет',
    });
    render(<RunsTable runs={[blocked]} selected={null} onSelect={() => undefined} />);
    expect(screen.getByText('заблокировано')).toBeInTheDocument();
    expect(screen.getByText(/в реестре фактов значения нет/)).toBeInTheDocument();
  });
});

describe('почему такое значение', () => {
  it('раскрывает цепочку до правила и факта', () => {
    render(<RunTrace trace={resultTrace()} />);
    // Итоговая строка и пояснение шага — оба содержат арифметику шага.
    expect(screen.getAllByText(/Высота этажа 3,3 м × 24 эт\. = 79,2 м$/)).toHaveLength(2);
    expect(screen.getByText('test.geometry.vertical_length@1')).toBeInTheDocument();
    expect(screen.getByText('Высота этажа: 3,3 м (заявлено: 3300 мм)')).toBeInTheDocument();
  });
});
