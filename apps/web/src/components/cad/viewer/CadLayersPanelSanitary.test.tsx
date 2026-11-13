import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mepLayerCounts } from '@/lib/cad/mep-layer-counts';
import { mepLayerTitle, presentMepLayers } from '@/lib/cad/mep-layers';

import { CadLayersPanel } from './CadLayersPanel';

const previewLayers = ['M-VK-V1', 'M-NODE', 'M-SAN-BATH', 'M-SAN-WC'];
const defs = presentMepLayers(previewLayers);
const names = defs.map((def) => def.name);

describe('CadLayersPanel: группа «Сантехника»', () => {
  it('слои приборов - отдельная группа последней, у пунктов число приборов', () => {
    const counts = mepLayerCounts(
      {
        layers: previewLayers,
        paths: [
          { layer: 2, closed: true },
          { layer: 2, closed: true },
          { layer: 3, closed: true },
        ],
      },
      names,
    );
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
          names,
          titles: defs.map(mepLayerTitle),
          visible: new Set(names.map((_, index) => index)),
          onToggle: vi.fn(),
          onSetHidden: vi.fn(),
          counts,
        }}
      />,
    );
    const headers = within(screen.getByTestId('mep-layers'))
      .getAllByRole('checkbox', { name: /^Группа «/ })
      .map((box) => box.getAttribute('aria-label'));
    expect(headers).toEqual(['Группа «Водоснабжение»', 'Группа «Узлы и стояки»', 'Группа «Сантехника»']);
    const group = screen.getByTestId('layer-group-mep-sanitary');
    const bath = within(group).getByRole('checkbox', { name: /Ванна · M-SAN-BATH/ }).closest('label');
    expect(within(bath as HTMLElement).getByTestId('layer-count')).toHaveTextContent('2');
    const wc = within(group).getByRole('checkbox', { name: /Унитаз · M-SAN-WC/ }).closest('label');
    expect(within(wc as HTMLElement).getByTestId('layer-count')).toHaveTextContent('1');
    // У слоёв трасс чисел нет.
    expect(within(screen.getByTestId('layer-group-mep-water')).queryByTestId('layer-count')).toBeNull();
  });
});
