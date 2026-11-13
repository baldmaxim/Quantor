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
      categories={{ monolithVertical: true, monolithColumn: true, slab: true, onChange }}
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
  it('строка «Плита» переключается, строки «Перемычки» нет (перемычка - часть стены)', () => {
    const onChange = vi.fn();
    mount(false, onChange);
    const slab = screen.getByRole('checkbox', { name: 'Плита' });
    expect(slab).toBeChecked();
    expect(screen.queryByRole('checkbox', { name: /Перемычки/ })).toBeNull();
    fireEvent.click(slab);
    expect(onChange).toHaveBeenLastCalledWith('slab', false);
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
