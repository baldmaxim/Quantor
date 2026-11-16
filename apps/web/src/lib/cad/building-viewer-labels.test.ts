import { describe, expect, it } from 'vitest';

import { createGroupLabels } from './building-viewer-labels';

describe('подписи групп над зданием', () => {
  it('у не поставленного на объект здания - вторая строка с пометкой и пунктирная рамка', () => {
    const host = document.createElement('div');
    const labels = createGroupLabels(host);
    labels.set([
      { key: 'p', text: 'Паркинг', x: 0, y: 0, z: 0, floorKey: 'p1:0:0' },
      {
        key: 'k6',
        text: 'Корп. 6',
        x: 0,
        y: 0,
        z: 0,
        floorKey: 'k6:0:0',
        note: 'не поставлен на объект',
      },
    ]);
    const [placed, lost] = [...host.children];
    expect(placed?.textContent).toBe('Паркинг');
    expect(placed?.className).not.toContain('border-dashed');
    expect(lost?.textContent).toBe('Корп. 6не поставлен на объект');
    expect(lost?.className).toContain('border-dashed');
    labels.dispose();
    expect(host.children).toHaveLength(0);
  });
});
