import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadLayersPanel } from './CadLayersPanel';

const mount = (patch: Partial<Parameters<typeof CadLayersPanel>[0]> = {}) => {
  const onToggleLayer = vi.fn();
  render(
    <CadLayersPanel
      layers={['WALLS', 'DOORS', 'TEXT']}
      visibleLayers={new Set([0, 2])}
      onToggleLayer={onToggleLayer}
      opacity={0.85}
      onOpacityChange={vi.fn()}
      cadShown
      previewAvailable
      pointCount={12345}
      cropAvailable
      cropVisible={false}
      onCropChange={vi.fn()}
      {...patch}
    />,
  );
  return { onToggleLayer };
};

describe('CadLayersPanel', () => {
  it('у каждого слоя свой цветной образец из токенов палитры по порядку', () => {
    mount();
    const swatches = screen.getAllByTestId('layer-swatch');
    expect(swatches).toHaveLength(3);
    expect(swatches.map((swatch) => swatch.getAttribute('style'))).toEqual([
      expect.stringContaining('var(--cad-layer-1)'),
      expect.stringContaining('var(--cad-layer-2)'),
      expect.stringContaining('var(--cad-layer-3)'),
    ]);
  });

  it('выключенный слой приглушён: образец бледный, имя зачёркнуто и серое', () => {
    mount();
    const [walls, doors] = screen.getAllByTestId('layer-swatch');
    expect(walls).toHaveAttribute('data-layer-on', 'true');
    expect(walls?.className).not.toContain('opacity-30');
    expect(doors).toHaveAttribute('data-layer-on', 'false');
    expect(doors?.className).toContain('opacity-30');
    expect(screen.getByText('DOORS').className).toContain('line-through');
    expect(screen.getByText('WALLS').className).not.toContain('line-through');
  });

  it('чекбокс слоя называется по имени слоя и переключает его', () => {
    const { onToggleLayer } = mount();
    expect(screen.getByRole('checkbox', { name: 'WALLS' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'DOORS' }));
    expect(onToggleLayer).toHaveBeenCalledWith(1);
  });

  it('непрозрачность, область проверки масштаба и число точек', () => {
    mount();
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: 'Область проверки масштаба на PDF' }),
    ).not.toBeChecked();
    expect(screen.getByText(/Точек в предпросмотре/)).toHaveTextContent('12');
  });

  it('геометрия CAD не показана: слоёв и ползунка нет, причина названа', () => {
    mount({ cadShown: false });
    expect(screen.queryByRole('slider')).toBeNull();
    expect(screen.queryByTestId('layer-swatch')).toBeNull();
    expect(screen.getByRole('note')).toHaveTextContent('режимах «CAD» и «Наложение»');
  });

  it('предпросмотра нет совсем: другая причина', () => {
    mount({ cadShown: false, previewAvailable: false, layers: [], pointCount: null });
    expect(screen.getByRole('note')).toHaveTextContent('предпросмотр геометрии не получен');
    expect(screen.queryByText(/Точек в предпросмотре/)).toBeNull();
  });
});
