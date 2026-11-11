import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { SheetList, type ISheetListPage } from './SheetList';

/** Список листов: ярлыки «Распознан» и «CAD» независимы, без признака ярлыка нет. */

const page = (overrides: Partial<ISheetListPage> = {}): ISheetListPage => ({
  id: 'sheet-1',
  index: 0,
  label: null,
  regionCount: 0,
  cad: false,
  ...overrides,
});

beforeAll(() => {
  // jsdom не реализует scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});

describe('SheetList', () => {
  it('лист с регионами и CAD показывает оба ярлыка', () => {
    render(
      <SheetList pages={[page({ regionCount: 5, cad: true })]} activeIndex={0} onSelect={vi.fn()} />,
    );
    expect(screen.getByText('Распознан')).toBeInTheDocument();
    expect(screen.getByText('CAD')).toBeInTheDocument();
  });

  it('лист без регионов и без CAD ярлыков не имеет', () => {
    render(<SheetList pages={[page()]} activeIndex={0} onSelect={vi.fn()} />);
    expect(screen.queryByText('Распознан')).not.toBeInTheDocument();
    expect(screen.queryByText('CAD')).not.toBeInTheDocument();
  });

  it('только CAD или только регионы дают один ярлык', () => {
    render(
      <SheetList
        pages={[
          page({ id: 'a', index: 0, cad: true }),
          page({ id: 'b', index: 1, regionCount: 2 }),
        ]}
        activeIndex={0}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getAllByText('CAD')).toHaveLength(1);
    expect(screen.getAllByText('Распознан')).toHaveLength(1);
  });

  it('клик по листу вызывает onSelect с индексом', async () => {
    const onSelect = vi.fn();
    render(
      <SheetList
        pages={[page({ id: 'a', index: 0 }), page({ id: 'b', index: 3 })]}
        activeIndex={0}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /Лист 4/ }));
    expect(onSelect).toHaveBeenCalledWith(3);
  });
});
