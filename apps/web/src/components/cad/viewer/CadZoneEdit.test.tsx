import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Camera } from '@/lib/viewer/camera';

import { CadZoneEdit } from './CadZoneEdit';
import { drag, stubPointerApi, tap, zoneFixture } from './zoneModeTestUtils';

const PAGE = { width: 1000, height: 1000 };

describe('CadZoneEdit', () => {
  beforeEach(stubPointerApi);

  const mount = (patch: Partial<Parameters<typeof CadZoneEdit>[0]> = {}) => {
    const camera = new Camera();
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(
      <CadZoneEdit
        camera={camera}
        page={PAGE}
        zones={[zoneFixture()]}
        zoneId="z1"
        saving={false}
        error={null}
        onSave={onSave}
        onCancel={onCancel}
        {...patch}
      />,
    );
    return { layer: screen.getByTestId('zone-edit'), onSave, onCancel, camera };
  };

  it('перетаскивание вершины меняет контур; Enter отдаёт его на сохранение', () => {
    const { layer, onSave } = mount();
    drag(layer, [600, 600], [650, 700]);
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave).toHaveBeenCalledWith([
      [0.2, 0.2],
      [0.6, 0.2],
      [0.65, 0.7],
      [0.2, 0.6],
    ]);
  });

  it('тяга за середину ребра добавляет вершину', () => {
    const { layer, onSave } = mount();
    drag(layer, [400, 200], [400, 100]);
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave).toHaveBeenCalledWith([
      [0.2, 0.2],
      [0.4, 0.1],
      [0.6, 0.2],
      [0.6, 0.6],
      [0.2, 0.6],
    ]);
  });

  it('вершина липнет к вершине другой зоны', () => {
    const other = zoneFixture({
      id: 'z2',
      points: [
        [0.8, 0.8],
        [0.9, 0.8],
        [0.9, 0.9],
      ],
    });
    const { layer, onSave } = mount({ zones: [zoneFixture(), other] });
    drag(layer, [600, 600], [803, 797]);
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave.mock.calls[0]?.[0]?.[2]).toEqual([0.8, 0.8]);
  });

  it('Delete убирает выбранную вершину, но не меньше трёх', () => {
    const { layer, onSave } = mount();
    tap(layer, 200, 600);
    fireEvent.keyDown(document, { key: 'Delete' });
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave).toHaveBeenLastCalledWith([
      [0.2, 0.2],
      [0.6, 0.2],
      [0.6, 0.6],
    ]);

    tap(layer, 600, 600);
    fireEvent.keyDown(document, { key: 'Backspace' });
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave.mock.calls[1]?.[0]).toHaveLength(3);
  });

  it('Delete без выбранной вершины ничего не удаляет', () => {
    const { onSave } = mount();
    fireEvent.keyDown(document, { key: 'Delete' });
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave.mock.calls[0]?.[0]).toHaveLength(4);
  });

  it('Esc и «Отмена» закрывают без сохранения', () => {
    const { onSave, onCancel } = mount();
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('«Сохранить» отдаёт контур; во время записи кнопка отключена', () => {
    const { onSave } = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it('отказ сервера показывается текстом', () => {
    mount({ error: 'Контур пересекает сам себя' });
    expect(screen.getByRole('alert')).toHaveTextContent('Контур пересекает сам себя');
  });

  it('перетаскивание мимо ручек двигает лист и контур не меняет', () => {
    const { layer, onSave, camera } = mount();
    drag(layer, [800, 800], [860, 830]);
    expect(camera.getState().offsetX).toBe(60);
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onSave.mock.calls[0]?.[0]).toHaveLength(4);
    expect(onSave.mock.calls[0]?.[0]?.[0]).toEqual([0.2, 0.2]);
  });

  it('клавиши в поле ввода режим не трогают', () => {
    const { onCancel } = mount();
    const input = document.createElement('input');
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onCancel).not.toHaveBeenCalled();
    input.remove();
  });
});
