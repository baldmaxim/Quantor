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
      mep={{
        names: defs.map((def) => def.name),
        titles: defs.map(mepLayerTitle),
        visible: new Set(visible),
        onToggle,
        onSetHidden,
      }}
    />,
  );
  return { onToggle, onSetHidden, group: screen.getByTestId('layer-group-mep-heating') };
};

describe('CadLayersPanel: группа «Трассы механики»', () => {
  it('слои трасс разложены по системам, слой подписан системой и именем', () => {
    const { group } = mount();
    expect(screen.getByText('Чертёж (DXF вида)')).toBeInTheDocument();
    expect(within(group).getByText('Отопление')).toBeInTheDocument();
    expect(within(group).getByRole('checkbox', { name: 'Отопление подача Т1 · M-OV-T1' })).toBeChecked();
    expect(within(group).getByText('2 / 2')).toBeInTheDocument();
    const headers = within(screen.getByTestId('mep-layers'))
      .getAllByRole('checkbox', { name: /^Группа «/ })
      .map((box) => box.getAttribute('aria-label'));
    expect(headers).toEqual(['Группа «Отопление»', 'Группа «Узлы и стояки»']);
  });

  it('пустые группы не выводятся', () => {
    mount();
    expect(screen.queryByTestId('layer-group-mep-water')).toBeNull();
    expect(screen.queryByTestId('layer-group-mep-vent')).toBeNull();
    expect(screen.queryByText('Водоснабжение')).toBeNull();
  });

  it('образец цвета - токен системы, выключенный слой приглушён', () => {
    mount([0, 2]);
    const swatches = within(screen.getByTestId('mep-layers')).getAllByTestId('layer-swatch');
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
    fireEvent.click(within(group).getByRole('checkbox', { name: 'Отопление обратка Т2 · M-OV-T2' }));
    expect(onToggle).toHaveBeenCalledWith(1);
  });

  it('общий выключатель группы гасит все её слои и не трогает чужие', () => {
    const shown = mount();
    fireEvent.click(within(shown.group).getByRole('checkbox', { name: 'Группа «Отопление»' }));
    expect(shown.onSetHidden).toHaveBeenCalledWith([0, 1], true);
  });

  it('все слои группы выключены - общий выключатель возвращает их', () => {
    const { onSetHidden, group } = mount([2]);
    fireEvent.click(within(group).getByRole('checkbox', { name: 'Группа «Отопление»' }));
    expect(onSetHidden).toHaveBeenCalledWith([0, 1], false);
  });

  it('часть слоёв группы скрыта - общий выключатель в неопределённом состоянии', () => {
    const { onSetHidden, group } = mount([0, 2]);
    const master = within(group).getByRole('checkbox', { name: 'Группа «Отопление»' });
    expect((master as HTMLInputElement).indeterminate).toBe(true);
    expect(master).not.toBeChecked();
    fireEvent.click(master);
    expect(onSetHidden).toHaveBeenCalledWith([0, 1], false);
  });

  it('в режиме 3D слои трасс доступны для переключения, подписи «только план» нет', () => {
    const onToggle = vi.fn();
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
        mode3d
        mep={{
          names: defs.map((def) => def.name),
          titles: defs.map(mepLayerTitle),
          visible: new Set([0, 1, 2]),
          onToggle,
          onSetHidden: vi.fn(),
        }}
      />,
    );
    const group = screen.getByTestId('mep-layers');
    const checkbox = within(group).getByRole('checkbox', { name: 'Отопление обратка Т2 · M-OV-T2' });
    expect(checkbox).not.toBeDisabled();
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith(1);
    expect(screen.queryByText('Трассы механики: только план')).toBeNull();
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
      />,
    );
    expect(screen.queryByTestId('mep-layers')).toBeNull();
  });
});
