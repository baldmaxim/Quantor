import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { IPipelineStep, PipelineStepKey, PipelineStepState } from '@/lib/cad/pipeline';
import { PIPELINE_STEP_LABELS } from '@/lib/cad/pipeline';

import { PipelineStepper } from './PipelineStepper';

const KEYS: readonly PipelineStepKey[] = [
  'calibration',
  'convert',
  'walls',
  'zones',
  'approval',
  'routes',
  'floor3d',
];

const stepsOf = (
  states: readonly PipelineStepState[],
  details: Partial<Record<PipelineStepKey, string>> = {},
): IPipelineStep[] =>
  KEYS.map((key, index) => ({
    key,
    label: PIPELINE_STEP_LABELS[key],
    state: states[index] ?? 'blocked',
    detail: details[key] ?? null,
  }));

const items = () => within(screen.getByRole('list', { name: 'Шаги конвейера' })).getAllByRole('listitem');

describe('PipelineStepper', () => {
  it('шесть шагов, 3D DXF в дорожке нет', () => {
    render(<PipelineStepper steps={stepsOf(['done', 'done', 'running', 'todo', 'blocked', 'blocked', 'todo'])} />);
    expect(items()).toHaveLength(6);
    expect(screen.queryByText('3D DXF')).not.toBeInTheDocument();
  });

  it('текущий шаг - первый не завершённый: aria-current и подсказка', () => {
    render(
      <PipelineStepper
        steps={stepsOf(['done', 'done', 'running', 'todo', 'blocked', 'blocked', 'blocked'], {
          walls: '40 %',
        })}
      />,
    );
    const current = items().filter((item) => item.getAttribute('aria-current') === 'step');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAttribute('title', 'Конструкции: идёт · 40 %');
    expect(within(current[0] as HTMLElement).getByText(': идёт')).toBeInTheDocument();
    // Процент вторым рядком под подписью.
    expect(within(current[0] as HTMLElement).getByText('40 %')).toBeInTheDocument();
  });

  it('все шаги готовы или пропущены: текущего нет', () => {
    render(<PipelineStepper steps={stepsOf(['done', 'done', 'skipped', 'skipped', 'skipped', 'skipped', 'todo'])} />);
    expect(items().some((item) => item.hasAttribute('aria-current'))).toBe(false);
  });

  it('слово состояния для чтения с экрана у каждого шага', () => {
    render(<PipelineStepper steps={stepsOf(['done', 'failed', 'review', 'todo', 'blocked', 'skipped', 'todo'])} />);
    const words = items().map((item) => within(item).getByText(/^: /).textContent);
    expect(words).toEqual([
      ': готово',
      ': ошибка',
      ': нужно решение',
      ': не начато',
      ': ждёт предыдущего шага',
      ': не требуется',
    ]);
  });

  it('человеческие шаги помечены для чтения с экрана', () => {
    render(<PipelineStepper steps={stepsOf(['todo', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked'])} />);
    const marked = items().filter((item) => within(item).queryByText(/действие человека/));
    expect(marked.map((item) => item.getAttribute('title')?.split(':')[0])).toEqual([
      'Калибровка',
      'Одобрение',
      'Трассы',
    ]);
  });

  it('линия перед шагом заполнена, если предыдущий готов', () => {
    render(<PipelineStepper steps={stepsOf(['done', 'done', 'todo', 'blocked', 'blocked', 'blocked', 'blocked'])} />);
    const connector = (index: number) =>
      items()[index]?.querySelector('span[aria-hidden="true"]') as HTMLElement | null;
    expect(connector(0)).toBeNull();
    expect(connector(1)?.className).toContain('bg-success');
    expect(connector(2)?.className).toContain('bg-success');
    expect(connector(3)?.className).toContain('bg-border');
  });
});
