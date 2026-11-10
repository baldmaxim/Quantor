import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  picker: vi.fn(),
  list: vi.fn(),
}));

vi.mock('@/components/cad/CadSheetPicker', () => ({
  CadSheetPicker: (props: {
    activePage: number | null;
    onOpenSheet: (page: number) => void;
    onWideChange?: (wide: boolean) => void;
  }) => {
    mocks.picker(props);
    return (
      <div>
        <button type="button" onClick={() => props.onOpenSheet(3)}>
          лист
        </button>
      </div>
    );
  },
}));
vi.mock('@/components/cad/CadJobList', () => ({
  CadJobList: (props: { selectedJobId: string | null; onSelect: (id: string) => void }) => {
    mocks.list(props);
    return (
      <button type="button" onClick={() => props.onSelect('j1')}>
        задание
      </button>
    );
  },
}));

import { WorkspaceCadLeft } from './WorkspaceCadLeft';

const handlers = () => ({
  onOpenSheet: vi.fn(),
  onSelectJob: vi.fn(),
});

const mount = (h = handlers()) => {
  render(
    <WorkspaceCadLeft
      projectId="p1"
      revisionId="r1"
      activePage={2}
      selectedJobId="j7"
      {...h}
    />,
  );
  return h;
};

beforeEach(() => vi.clearAllMocks());

describe('WorkspaceCadLeft', () => {
  it('подвкладки «Листы» и «Задания»; открыты листы', () => {
    mount();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Листы',
      'Задания',
    ]);
    expect(screen.getByRole('tab', { name: 'Листы' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('лист')).toBeVisible();
    expect(screen.queryByText('задание')).toBeNull();
  });

  it('листы получают открытую страницу и открывают лист в рабочей области', () => {
    const h = mount();
    expect(mocks.picker.mock.calls.at(-1)?.[0]).toMatchObject({ activePage: 2 });
    fireEvent.click(screen.getByText('лист'));
    expect(h.onOpenSheet).toHaveBeenCalledWith(3);
  });

  it('вкладка «Задания»: список с выбранным заданием, выбор уходит наружу; листы не теряются', () => {
    const h = mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Задания' }));
    expect(mocks.list.mock.calls.at(-1)?.[0]).toMatchObject({ selectedJobId: 'j7' });
    fireEvent.click(screen.getByText('задание'));
    expect(h.onSelectJob).toHaveBeenCalledWith('j1');
    // листы остались смонтированными, но скрыты
    expect(screen.getByText('лист')).not.toBeVisible();

    fireEvent.click(screen.getByRole('tab', { name: 'Листы' }));
    expect(screen.getByText('лист')).toBeVisible();
  });

  it('признак широкой колонки от списка листов уходит наружу', () => {
    const onWideChange = vi.fn();
    render(
      <WorkspaceCadLeft
        projectId="p1"
        revisionId="r1"
        activePage={2}
        selectedJobId={null}
        onOpenSheet={vi.fn()}
        onSelectJob={vi.fn()}
        onWideChange={onWideChange}
      />,
    );
    mocks.picker.mock.calls.at(-1)?.[0].onWideChange?.(true);
    expect(onWideChange).toHaveBeenCalledWith(true);
  });

  it('блока «Исходный PDF» нет', () => {
    mount();
    expect(screen.queryByText(/Исходный PDF/)).toBeNull();
    expect(screen.queryByRole('group')).toBeNull();
  });
});
