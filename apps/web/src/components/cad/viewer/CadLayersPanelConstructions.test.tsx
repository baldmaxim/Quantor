import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadLayersPanel } from './CadLayersPanel';

const mount = (constructions: { visible: boolean; onVisibleChange: (value: boolean) => void } | null) =>
  render(
    <CadLayersPanel
      layers={['WALLS']}
      visibleLayers={new Set([0])}
      onToggleLayer={vi.fn()}
      onSetLayersHidden={vi.fn()}
      pdfOpacity={1}
      onPdfOpacityChange={vi.fn()}
      pdfOpacityActive
      cadShown
      previewAvailable
      pointCount={null}
      cropAvailable={false}
      cropVisible={false}
      onCropChange={vi.fn()}
      regionsVisible={false}
      onRegionsVisibleChange={vi.fn()}
      regionsAvailable
      constructions={constructions}
    />,
  );

describe('CadLayersPanel: переключатель «Конструкции»', () => {
  it('галка отражает видимость и переключает слой', () => {
    const onVisibleChange = vi.fn();
    mount({ visible: true, onVisibleChange });
    const box = screen.getByRole('checkbox', { name: 'Конструкции' });
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(onVisibleChange).toHaveBeenCalledWith(false);
  });

  it('конструкций нет - переключателя нет', () => {
    mount(null);
    expect(screen.queryByRole('checkbox', { name: 'Конструкции' })).toBeNull();
  });
});
