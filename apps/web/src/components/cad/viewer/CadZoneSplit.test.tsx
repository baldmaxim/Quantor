import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SPLIT_OUTSIDE_TEXT } from '@/lib/cad/zone-split';
import { Camera } from '@/lib/viewer/camera';

import { CadZoneSplit, type ISplitParts } from './CadZoneSplit';
import { stubPointerApi, tap, zoneFixture } from './zoneModeTestUtils';

const PAGE = { width: 1000, height: 1000 };

const rounded = (ring: readonly (readonly [number, number])[]) =>
  ring.map(([x, y]) => [Math.round(x * 1e9) / 1e9, Math.round(y * 1e9) / 1e9]);

describe('CadZoneSplit', () => {
  beforeEach(stubPointerApi);

  const mount = () => {
    const camera = new Camera();
    const onApply = vi.fn<(parts: ISplitParts) => void>();
    const onCancel = vi.fn();
    render(
      <CadZoneSplit
        camera={camera}
        page={PAGE}
        zones={[zoneFixture()]}
        zoneId="z1"
        saving={false}
        error={null}
        onApply={onApply}
        onCancel={onCancel}
      />,
    );
    return { layer: screen.getByTestId('zone-split'), onApply, onCancel };
  };

  it('две точки на границе делят зону: большая часть остаётся, меньшая - новая', () => {
    const { layer, onApply } = mount();
    tap(layer, 300, 200); // верхнее ребро, левая треть
    expect(onApply).not.toHaveBeenCalled();
    tap(layer, 300, 600); // нижнее ребро
    expect(onApply).toHaveBeenCalledTimes(1);
    const parts = onApply.mock.calls[0]?.[0];
    // Левая часть 0.1 x 0.4, правая 0.3 x 0.4: правая остаётся исходной.
    expect(rounded(parts?.keep ?? [])).toEqual([
      [0.3, 0.2],
      [0.6, 0.2],
      [0.6, 0.6],
      [0.3, 0.6],
    ]);
    expect(rounded(parts?.created ?? [])).toEqual([
      [0.3, 0.6],
      [0.2, 0.6],
      [0.2, 0.2],
      [0.3, 0.2],
    ]);
  });

  it('точка вне границы не принимается: сообщение, первая точка не ставится', () => {
    const { layer, onApply } = mount();
    tap(layer, 400, 400);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Точка должна лежать на границе помещения.',
    );
    tap(layer, 400, 600);
    tap(layer, 400, 200);
    // Первой точкой стала только (400, 600): разрез состоялся по прямой через зону.
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it('линия вдоль одного ребра отклоняется сообщением, применения нет', () => {
    const { layer, onApply } = mount();
    tap(layer, 300, 200);
    tap(layer, 500, 200);
    expect(screen.getByRole('alert')).toHaveTextContent(SPLIT_OUTSIDE_TEXT);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('Esc сначала сбрасывает первую точку, затем закрывает режим', () => {
    const { layer, onApply, onCancel } = mount();
    tap(layer, 300, 200);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).not.toHaveBeenCalled();
    // Первая точка сброшена: следующий щелчок снова первый, разреза нет.
    tap(layer, 300, 600);
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('«Отмена» закрывает режим', () => {
    const { onCancel } = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
