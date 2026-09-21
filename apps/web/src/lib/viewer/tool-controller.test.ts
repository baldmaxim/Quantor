import { describe, expect, it } from 'vitest';

import type { NormalizedPoint } from './coordinates';
import { ToolController } from './tool-controller';

/**
 * Контроллер инструментов обмера.
 *
 * Проверяется то, что нашла живая приёмка промта 02: черновик и выбор принадлежат листу,
 * на котором их начали, и при переходе на другой лист обязаны исчезнуть. Пока сброса не
 * было, начатая на листе 1 ломаная доживала до листа 2, и Enter сохранял её туда — с
 * координатами первого листа.
 */

const point = (x: number, y: number): NormalizedPoint => ({ x, y });

describe('смена листа', () => {
  it('сбрасывает черновик', () => {
    const tools = new ToolController('polyline');
    tools.send({ type: 'pointerDown', point: point(0.2, 0.3) });
    tools.send({ type: 'pointerDown', point: point(0.3, 0.3) });
    expect(tools.getState().points).toHaveLength(2);

    tools.resetForSheetChange();

    expect(tools.getState().points).toHaveLength(0);
  });

  it('снимает выбор измерения прежнего листа', () => {
    const tools = new ToolController('select');
    tools.send({ type: 'selectMeasurement', measurementId: 'm-1' });
    expect(tools.getState().selectedId).toBe('m-1');

    tools.resetForSheetChange();

    expect(tools.getState().selectedId).toBeNull();
  });

  it('не меняет выбранный инструмент: лист другой, работа та же', () => {
    const tools = new ToolController('polygon');

    tools.resetForSheetChange();

    expect(tools.getState().mode).toBe('polygon');
  });
});
