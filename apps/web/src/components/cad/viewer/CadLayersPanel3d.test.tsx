import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadLayersPanel } from './CadLayersPanel';

const LAYERS = ['01_КЛАДКА', '03_ДВЕРИ', '04_ОСИ'];

const mount = (mode3d: boolean, onChange = vi.fn(), onToggleLayer = vi.fn()) =>
  render(
    <CadLayersPanel
      layers={LAYERS}
      visibleLayers={new Set([0, 1, 2])}
      onToggleLayer={onToggleLayer}
      onSetLayersHidden={vi.fn()}
      mode3d={mode3d}
      categories={{ slab: true, lintel: false, onChange }}
      pdfOpacity={1}
      onPdfOpacityChange={vi.fn()}
      pdfOpacityActive
      cadShown
      previewAvailable
      pointCount={null}
      cropAvailable={false}
      cropVisible={false}
      onCropChange={vi.fn()}
    />,
  );

describe('CadLayersPanel: категории и режим 3D', () => {
  it('строки «Плита» и «Перемычки» отражают состояние и переключаются', () => {
    const onChange = vi.fn();
    mount(false, onChange);
    const slab = screen.getByRole('checkbox', { name: 'Плита' });
    const lintel = screen.getByRole('checkbox', { name: /Перемычки/ });
    expect(slab).toBeChecked();
    expect(lintel).not.toBeChecked();
    fireEvent.click(slab);
    expect(onChange).toHaveBeenLastCalledWith('slab', false);
    fireEvent.click(lintel);
    expect(onChange).toHaveBeenLastCalledWith('lintel', true);
  });

  it('в плане все слои DXF доступны', () => {
    mount(false);
    for (const name of LAYERS) expect(screen.getByRole('checkbox', { name })).toBeEnabled();
    expect(screen.queryByText('только план')).toBeNull();
  });

  it('в 3D слои без категории неактивны с пометкой «только план», слои категорий работают', () => {
    const onToggleLayer = vi.fn();
    mount(true, vi.fn(), onToggleLayer);
    expect(screen.getByRole('checkbox', { name: /04_ОСИ/ })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: '01_КЛАДКА' })).toBeEnabled();
    expect(screen.getByRole('checkbox', { name: '03_ДВЕРИ' })).toBeEnabled();
    expect(screen.getAllByText('только план')).toHaveLength(1);
    fireEvent.click(screen.getByRole('checkbox', { name: '01_КЛАДКА' }));
    expect(onToggleLayer).toHaveBeenCalledWith(0);
  });
});
