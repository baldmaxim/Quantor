import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mepLayerTitle, presentMepLayers } from '@/lib/cad/mep-layers';

import { CadLayersPanel } from './CadLayersPanel';

const defs = presentMepLayers(['M-OV-T1', 'M-OV-T2', 'M-NODE']);

const mount = (visible: number[] = [0, 1, 2]) => {
  const onToggle = vi.fn();
  const onSetHidden = vi.fn();
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
      mep={{
        names: defs.map((def) => def.name),
        titles: defs.map(mepLayerTitle),
        visible: new Set(visible),
        onToggle,
        onSetHidden,
      }}
    />,
  );
  return { onToggle, onSetHidden, group: screen.getByTestId('layer-group-mep') };
};

describe('CadLayersPanel: группа «Трассы механики»', () => {
  it('рядом с чертежом DXF стоит вторая группа, слой подписан системой и именем', () => {
    const { group } = mount();
    expect(screen.getByText('Чертёж (DXF вида)')).toBeInTheDocument();
    expect(within(group).getByText('Трассы механики')).toBeInTheDocument();
    expect(within(group).getByRole('checkbox', { name: 'Отопление подача · M-OV-T1' })).toBeChecked();
    expect(within(group).getByText('3 / 3')).toBeInTheDocument();
  });

  it('образец цвета - токен системы, выключенный слой приглушён', () => {
    const { group } = mount([0, 2]);
    const swatches = within(group).getAllByTestId('layer-swatch');
    expect(swatches.map((swatch) => swatch.getAttribute('style'))).toEqual([
      expect.stringContaining('var(--cad-mep-ov-t1)'),
      expect.stringContaining('var(--cad-mep-ov-t2)'),
      expect.stringContaining('var(--cad-mep-node)'),
    ]);
    expect(swatches[1]).toHaveAttribute('data-layer-on', 'false');
    expect(swatches[1]?.className).toContain('opacity-30');
    expect(swatches[0]?.className).not.toContain('opacity-30');
  });

  it('слой включается и выключается своим чекбоксом', () => {
    const { onToggle, group } = mount();
    fireEvent.click(within(group).getByRole('checkbox', { name: 'Отопление обратка · M-OV-T2' }));
    expect(onToggle).toHaveBeenCalledWith(1);
  });

  it('общий выключатель группы гасит все слои, а при погашенных - включает', () => {
    const shown = mount();
    fireEvent.click(within(shown.group).getByRole('checkbox', { name: 'Группа «Трассы механики»' }));
    expect(shown.onSetHidden).toHaveBeenCalledWith([0, 1, 2], true);
  });

  it('все слои выключены - общий выключатель возвращает их', () => {
    const { onSetHidden, group } = mount([]);
    fireEvent.click(within(group).getByRole('checkbox', { name: 'Группа «Трассы механики»' }));
    expect(onSetHidden).toHaveBeenCalledWith([0, 1, 2], false);
  });

  it('без трасс группы нет', () => {
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
      />,
    );
    expect(screen.queryByTestId('mep-layers')).toBeNull();
  });
});
