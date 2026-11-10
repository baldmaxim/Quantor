import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DrawingViewport } from './DrawingViewport';
import { Camera } from '@/lib/viewer/camera';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

/**
 * Дополнительный слой холста (CAD-просмотр): по умолчанию его нет, с рисовальщиком он
 * рисуется по размещению листа и догоняет камеру.
 */

const SHEET = { pageIndex: 0, width: 1000, height: 500 };

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    // Любой метод контекста - пустышка: проверяется протокол слоя, а не пиксели.
    return new Proxy(
      { canvas: this },
      { get: (target, key) => (key in target ? Reflect.get(target, key) : () => undefined), set: () => true },
    ) as unknown as CanvasRenderingContext2D;
  } as unknown as typeof HTMLCanvasElement.prototype.getContext);
  vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(800);
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(600);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const mount = (extraPainter?: LayerPainter | null, pageOpacity?: number) =>
  render(
    <DrawingViewport
      backend={null}
      sheet={SHEET}
      regions={[]}
      hiddenTypes={new Set()}
      overlayVisible={false}
      selectedId={null}
      onSelect={vi.fn()}
      camera={new Camera()}
      tool="pan"
      extraPainter={extraPainter}
      pageOpacity={pageOpacity}
    />,
  );

const painterSpy = () => ({
  paint: vi.fn<LayerPainter['paint']>(),
  touches: vi.fn<LayerPainter['touches']>(() => true),
});

describe('дополнительный слой DrawingViewport', () => {
  it('без рисовальщика холст скрыт и не рисуется', () => {
    mount();
    expect(screen.getByTestId('extra-layer').className).toContain('hidden');
  });

  it('с рисовальщиком слой виден и рисуется целиком по размещению листа', async () => {
    const painter = painterSpy();
    mount(painter);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });

    expect(screen.getByTestId('extra-layer').className).not.toContain('hidden');
    expect(painter.paint).toHaveBeenCalled();
    const [, placement, , area] = painter.paint.mock.calls[0] ?? [];
    expect(area).toBeNull();
    expect(placement).toMatchObject({ rotation: 0 });
    expect((placement as { width: number }).width).toBeGreaterThan(0);
  });

  it('новый рисовальщик перерисовывает слой', async () => {
    const first = painterSpy();
    const second = painterSpy();
    const view = mount(first);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });

    view.rerender(
      <DrawingViewport
        backend={null}
        sheet={SHEET}
        regions={[]}
        hiddenTypes={new Set()}
        overlayVisible={false}
        selectedId={null}
        onSelect={vi.fn()}
        camera={new Camera()}
        tool="pan"
        extraPainter={second}
      />,
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });

    expect(second.paint).toHaveBeenCalled();
  });
});

describe('непрозрачность подложки PDF', () => {
  const stackOf = () => screen.getByTestId('viewport').firstElementChild as HTMLElement;

  it('по умолчанию подложка непрозрачна: свойство не ставится', () => {
    mount();
    expect(stackOf().style.opacity).toBe('');
  });

  it('значение ставится CSS на стопку страницы; слои наложения остаются непрозрачными', () => {
    mount(null, 0.4);
    expect(stackOf().style.opacity).toBe('0.4');
    expect(screen.getByTestId('extra-layer').style.opacity).toBe('');
    expect(screen.getByTestId('regions-layer').style.opacity).toBe('');
  });

  it('ноль скрывает подложку, единица возвращает', () => {
    const view = mount(null, 0);
    expect(stackOf().style.opacity).toBe('0');
    view.rerender(
      <DrawingViewport
        backend={null}
        sheet={SHEET}
        regions={[]}
        hiddenTypes={new Set()}
        overlayVisible={false}
        selectedId={null}
        onSelect={vi.fn()}
        camera={new Camera()}
        tool="pan"
        pageOpacity={1}
      />,
    );
    expect(stackOf().style.opacity).toBe('');
  });
});
