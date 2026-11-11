import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_ZONE_VIEW } from '@/lib/cad/zone-view';

import { CadZoneLayers, type ICadZoneLayers } from './CadZoneLayers';

const mount = (patch: Partial<ICadZoneLayers> = {}) => {
  const props: ICadZoneLayers = {
    categories: [
      { category: 'wet', count: 3 },
      { category: 'kitchen', count: 12 },
    ],
    view: DEFAULT_ZONE_VIEW,
    onSetHidden: vi.fn(),
    onColorModeChange: vi.fn(),
    onLabelsOnChange: vi.fn(),
    onLabelChange: vi.fn(),
    ...patch,
  };
  render(<CadZoneLayers {...props} />);
  return props;
};

describe('CadZoneLayers', () => {
  it('пункты с числом зон и образцами цвета', () => {
    mount();
    const group = screen.getByTestId('layer-group-zones');
    expect(within(group).getByText('Кухни (12)')).toBeTruthy();
    expect(within(group).getByText('Санузлы и ванные (3)')).toBeTruthy();
    expect(within(group).getAllByTestId('layer-swatch')).toHaveLength(2);
  });

  it('галка категории скрывает её', () => {
    const props = mount();
    fireEvent.click(screen.getByLabelText(/Кухни \(12\)/));
    expect(props.onSetHidden).toHaveBeenCalledWith(['kitchen'], true);
  });

  it('скрытая категория показывается обратно', () => {
    const props = mount({ view: { ...DEFAULT_ZONE_VIEW, hidden: new Set(['wet']) } });
    fireEvent.click(screen.getByLabelText(/Санузлы и ванные \(3\)/));
    expect(props.onSetHidden).toHaveBeenCalledWith(['wet'], false);
  });

  it('групповой флажок скрывает все категории разом', () => {
    const props = mount();
    fireEvent.click(screen.getByLabelText('Группа «Зоны»'));
    expect(props.onSetHidden).toHaveBeenCalledWith(['wet', 'kitchen'], true);
  });

  it('радиокнопки переключают окраску', () => {
    const props = mount();
    expect(screen.getByLabelText('По типу помещения')).toHaveProperty('checked', true);
    fireEvent.click(screen.getByLabelText('По квартирам'));
    expect(props.onColorModeChange).toHaveBeenCalledWith('apartment');
  });

  it('флажки подписей; при выключенных подписях недоступны', () => {
    const props = mount();
    fireEvent.click(screen.getByLabelText('Название'));
    expect(props.onLabelChange).toHaveBeenCalledWith('name', true);
    fireEvent.click(screen.getByLabelText('Подписи зон'));
    expect(props.onLabelsOnChange).toHaveBeenCalledWith(false);
  });

  it('подписи выключены - частные флажки disabled', () => {
    mount({ view: { ...DEFAULT_ZONE_VIEW, labelsOn: false } });
    expect(screen.getByLabelText('Площадь')).toHaveProperty('disabled', true);
  });
});
