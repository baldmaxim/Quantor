import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { constructionsRead } from '@/lib/cad/constructions-fixtures';
import { countRebuildRemarks } from '@/lib/cad/remarks';

import { ConstructionsPanel } from './ConstructionsPanel';
import type { IWorkspaceCadConstructions } from './types';

const props = (patch: Partial<IWorkspaceCadConstructions> = {}): IWorkspaceCadConstructions => ({
  status: 'ready',
  data: constructionsRead({}),
  notReadyText: null,
  loadError: null,
  onReload: vi.fn(),
  calculating: false,
  actionError: null,
  onCompute: vi.fn(),
  levelsSaving: false,
  onSaveLevels: vi.fn(),
  activeGroup: null,
  onSelectGroup: vi.fn(),
  ...patch,
});

describe('countRebuildRemarks', () => {
  it('считает только открытые замечания подходящих типов', () => {
    expect(
      countRebuildRemarks([
        { type: 'missing_wall', status: 'open' },
        { type: 'false_wall', status: 'open' },
        { type: 'missing_door', status: 'resolved' },
        { type: 'monolith', status: 'open' },
      ]),
    ).toBe(2);
  });
});

describe('ConstructionsPanel: перестроение по замечаниям', () => {
  it('кнопка с числом замечаний запускает перестроение', () => {
    const onRebuild = vi.fn();
    render(<ConstructionsPanel {...props({ rebuild: { count: 3, pending: false, onRebuild } })} />);
    const button = screen.getByRole('button', { name: 'Перестроить по замечаниям (3)' });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onRebuild).toHaveBeenCalledTimes(1);
  });

  it('нет подходящих замечаний или идёт расчёт - кнопка заблокирована', () => {
    const { rerender } = render(
      <ConstructionsPanel {...props({ rebuild: { count: 0, pending: false, onRebuild: vi.fn() } })} />,
    );
    expect(screen.getByRole('button', { name: 'Перестроить по замечаниям (0)' })).toBeDisabled();
    rerender(
      <ConstructionsPanel
        {...props({ calculating: true, rebuild: { count: 2, pending: false, onRebuild: vi.fn() } })}
      />,
    );
    expect(screen.getByRole('button', { name: 'Перестроить по замечаниям (2)' })).toBeDisabled();
  });

  it('без rebuild кнопки нет', () => {
    render(<ConstructionsPanel {...props()} />);
    expect(screen.queryByRole('button', { name: /Перестроить по замечаниям/ })).toBeNull();
    expect(screen.queryByTestId('constructions-hints-result')).toBeNull();
  });

  it('блок «Итог подсказок»: тип, статус, добавлено и снято', () => {
    const data = constructionsRead({
      hints_applied: [
        { id: 'a', type: 'missing_wall', status: 'applied', added_ids: ['w1', 'w2'], removed_ids: [] },
        {
          id: 'b',
          type: 'missing_door',
          status: 'no_candidate',
          added_ids: [],
          removed_ids: [],
          reason: 'в рамке нет разрыва',
        },
        { id: 'c', type: 'false_wall', status: 'applied', added_ids: [], removed_ids: ['w9'] },
      ],
    });
    render(<ConstructionsPanel {...props({ data })} />);
    const rows = screen.getAllByTestId('hint-result');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('Нет стены')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('применена')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('добавлено: 2, снято: 0')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('кандидата нет: в рамке нет разрыва')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('добавлено: 0, снято: 1')).toBeInTheDocument();
  });
});
