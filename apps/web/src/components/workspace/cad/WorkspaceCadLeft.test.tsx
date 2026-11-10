import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  picker: vi.fn(),
  list: vi.fn(),
  source: vi.fn(),
}));

vi.mock('@/components/cad/CadSourcePicker', () => ({
  CadSourcePicker: (props: { selectedRevisionId: string | null; onSelect: (id: string) => void }) => {
    mocks.source(props);
    return (
      <button type="button" onClick={() => props.onSelect('r2')}>
        источник
      </button>
    );
  },
}));
vi.mock('@/components/cad/CadSheetPicker', () => ({
  CadSheetPicker: (props: {
    activePage: number | null;
    onOpenSheet: (page: number) => void;
    onJobCreated: (jobId: string, pages: readonly number[]) => void;
  }) => {
    mocks.picker(props);
    return (
      <div>
        <button type="button" onClick={() => props.onOpenSheet(3)}>
          лист
        </button>
        <button type="button" onClick={() => props.onJobCreated('j9', [3])}>
          запуск
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
  onJobCreated: vi.fn(),
  onSourceSelect: vi.fn(),
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

  it('создание задания передаётся наружу вместе со страницами', () => {
    const h = mount();
    fireEvent.click(screen.getByText('запуск'));
    expect(h.onJobCreated).toHaveBeenCalledWith('j9', [3]);
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

  it('источник PDF: выбранная ревизия — текущая, выбор другой уходит наружу', () => {
    const h = mount();
    expect(mocks.source.mock.calls.at(-1)?.[0]).toMatchObject({ selectedRevisionId: 'r1' });
    fireEvent.click(screen.getByText('источник'));
    expect(h.onSourceSelect).toHaveBeenCalledWith('r2');
  });
});
