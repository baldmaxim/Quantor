import { render } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it } from 'vitest';

import { Camera } from '@/lib/viewer/camera';

import { usePinchZoom } from './usePinchZoom';

const Host = ({ camera, onChild }: { camera: Camera; onChild: (type: string) => void }) => {
  const ref = useRef<HTMLDivElement>(null);
  usePinchZoom(ref, camera);
  return (
    <div ref={ref} data-testid="host">
      <div
        data-testid="child"
        onPointerDown={() => onChild('down')}
        onPointerMove={() => onChild('move')}
      />
    </div>
  );
};

const fire = (target: Element, type: string, id: number, x: number, y: number) => {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, { pointerId: id, pointerType: 'touch', clientX: x, clientY: y });
  target.dispatchEvent(event);
};

describe('usePinchZoom', () => {
  it('щипок увеличивает масштаб пропорционально расстоянию между пальцами', () => {
    const camera = new Camera();
    const seen: string[] = [];
    const { getByTestId } = render(<Host camera={camera} onChild={(t) => seen.push(t)} />);
    const child = getByTestId('child');

    fire(child, 'pointerdown', 1, 100, 100);
    fire(child, 'pointerdown', 2, 200, 100);
    fire(child, 'pointermove', 1, 50, 100);
    fire(child, 'pointermove', 2, 250, 100);

    expect(camera.getState().scale).toBeCloseTo(2, 5);
  });

  it('первый палец доходит до холста, второй и движения щипка - нет', () => {
    const camera = new Camera();
    const seen: string[] = [];
    const { getByTestId } = render(<Host camera={camera} onChild={(t) => seen.push(t)} />);
    const child = getByTestId('child');

    fire(child, 'pointerdown', 1, 100, 100);
    fire(child, 'pointerdown', 2, 200, 100);
    fire(child, 'pointermove', 1, 90, 100);
    fire(child, 'pointermove', 2, 210, 100);

    expect(seen).toEqual(['down']);
  });

  it('один палец камеру не трогает', () => {
    const camera = new Camera();
    const { getByTestId } = render(<Host camera={camera} onChild={() => undefined} />);
    const child = getByTestId('child');

    fire(child, 'pointerdown', 1, 100, 100);
    fire(child, 'pointermove', 1, 150, 150);

    expect(camera.getState()).toEqual({ scale: 1, offsetX: 0, offsetY: 0 });
  });

  it('после щипка оставшийся палец не двигает холст', () => {
    const camera = new Camera();
    const seen: string[] = [];
    const { getByTestId } = render(<Host camera={camera} onChild={(t) => seen.push(t)} />);
    const child = getByTestId('child');

    fire(child, 'pointerdown', 1, 100, 100);
    fire(child, 'pointerdown', 2, 200, 100);
    fire(child, 'pointerup', 2, 200, 100);
    fire(child, 'pointermove', 1, 300, 300);

    expect(seen).toEqual(['down']);
  });
});
