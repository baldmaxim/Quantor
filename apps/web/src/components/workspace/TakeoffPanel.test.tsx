import type { TakeoffItemQuantityRead, TakeoffItemRead } from '@quantor/api-client';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { TakeoffPanel } from './TakeoffPanel';

/**
 * Панель строк обмера.
 *
 * Здесь проверяется то, что добавлено промтом 02: выгрузка листа предлагается только
 * тогда, когда её есть чем наполнить, и ведёт на серверный отчёт, а не на пересчёт в
 * браузере.
 */

const item = (overrides: Partial<TakeoffItemRead> = {}): TakeoffItemRead => ({
  id: 'item-1',
  project_id: 'p-1',
  name: 'Полы',
  code: null,
  geometry_type: 'polygon',
  display_unit: 'm2',
  color_key: 'accent',
  ordinal: 1,
  archived_at: null,
  created_by: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  ...overrides,
});

const total = (overrides: Partial<TakeoffItemQuantityRead> = {}): TakeoffItemQuantityRead => ({
  takeoff_item_id: 'item-1',
  unit: 'm2',
  canonical_unit: 'mm2',
  value: '12',
  canonical_value: '12000000',
  rule_key: 'area.v1',
  measurement_count: 1,
  unavailable_count: 0,
  invalid_count: 0,
  ...overrides,
});

const props = {
  items: [item()],
  activeItemId: 'item-1',
  counts: { 'item-1': 1 },
  totals: { 'item-1': total() },
  canEdit: true,
  pending: false,
  onSelect: vi.fn(),
  onCreate: vi.fn(),
  onRename: vi.fn(),
  onArchive: vi.fn(),
};

describe('панель обмеров', () => {
  it('предлагает выгрузку листа ссылкой на сервер', () => {
    render(
      <TakeoffPanel {...props} exportHref="http://api.test/api/v1/sheets/s-1/takeoff-export.csv" />,
    );

    expect(screen.getByRole('link', { name: /Выгрузить CSV/ })).toHaveAttribute(
      'href',
      'http://api.test/api/v1/sheets/s-1/takeoff-export.csv',
    );
  });

  it('без измерений выгружать нечего — ссылки нет', () => {
    render(<TakeoffPanel {...props} counts={{}} totals={{}} exportHref={null} />);

    expect(screen.queryByRole('link', { name: /Выгрузить/ })).not.toBeInTheDocument();
  });

  it('итог показывает величину, а не число измерений', () => {
    render(<TakeoffPanel {...props} exportHref={null} />);

    expect(screen.getByText('12 м²')).toBeInTheDocument();
  });

  it('измерения без масштаба считаются отдельно и не превращаются в ноль', () => {
    render(
      <TakeoffPanel
        {...props}
        counts={{ 'item-1': 3 }}
        totals={{ 'item-1': total({ measurement_count: 1, unavailable_count: 2 }) }}
        exportHref={null}
      />,
    );

    expect(screen.getByText(/\+2 без масштаба/)).toBeInTheDocument();
  });

  /**
   * Строку заводит и инструмент на чертеже, а имя ей придумывает сервер: «Линия 1» уходит
   * в выгрузку как есть, поэтому переименование должно быть под рукой — в самой строке.
   */
  it('двойной щелчок по имени открывает поле и сохраняет новое название', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(<TakeoffPanel {...props} onRename={onRename} exportHref={null} />);

    await user.dblClick(screen.getByText('Полы'));
    const field = screen.getByRole('textbox', { name: /Название строки/ });
    await user.clear(field);
    await user.type(field, '  Перегородка ПГ-1  {Enter}');

    expect(onRename).toHaveBeenCalledWith('item-1', 'Перегородка ПГ-1');
  });

  it('Esc закрывает поле, не трогая название', async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(<TakeoffPanel {...props} onRename={onRename} exportHref={null} />);

    await user.dblClick(screen.getByText('Полы'));
    await user.type(screen.getByRole('textbox', { name: /Название строки/ }), 'Другое{Escape}');

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText('Полы')).toBeInTheDocument();
  });
});
