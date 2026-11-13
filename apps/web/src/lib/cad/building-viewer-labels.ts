import * as THREE from 'three';

import type { IViewerGroupLabel } from './building-viewer-geometry';

/**
 * Подписи групп над зданием («Весь объект»): HTML-плашки поверх холста, положение - проекция точки
 * сцены на экран при каждой отрисовке. Спрайты с текстом пришлось бы перерисовывать под тему и шрифт;
 * плашка красится классами токенов. Элементы живут в `host` и событий мыши не ловят.
 */

const LABEL_CLASS =
  'pointer-events-none absolute top-0 left-0 z-10 max-w-[200px] truncate rounded-[var(--radius-sm)] border border-border bg-surface/90 px-[var(--s-3)] py-[var(--s-1)] text-xs font-medium whitespace-nowrap text-text';

export interface IGroupLabels {
  /** Новый набор подписей; прежние убираются. */
  set: (labels: readonly IViewerGroupLabel[]) => void;
  /** Ставит плашки по камере; `shiftOf` - подъём этажа при разнесении, м. */
  update: (camera: THREE.Camera, width: number, height: number, shiftOf: (floorKey: string) => number) => void;
  dispose: () => void;
}

export const createGroupLabels = (host: HTMLElement): IGroupLabels => {
  let items: { label: IViewerGroupLabel; element: HTMLDivElement }[] = [];
  const point = new THREE.Vector3();

  const clear = (): void => {
    for (const item of items) item.element.remove();
    items = [];
  };

  return {
    set: (labels) => {
      clear();
      items = labels.map((label) => {
        const element = document.createElement('div');
        element.className = LABEL_CLASS;
        element.textContent = label.text;
        element.title = label.text;
        host.appendChild(element);
        return { label, element };
      });
    },
    update: (camera, width, height, shiftOf) => {
      for (const { label, element } of items) {
        point.set(label.x, label.y + shiftOf(label.floorKey), label.z).project(camera);
        // За камерой или далеко за краем кадра плашка не нужна.
        const hidden = point.z > 1 || Math.abs(point.x) > 1.5 || Math.abs(point.y) > 1.5;
        element.style.visibility = hidden ? 'hidden' : 'visible';
        if (hidden) continue;
        const x = (point.x * 0.5 + 0.5) * width;
        const y = (-point.y * 0.5 + 0.5) * height;
        // Положение зависит от камеры - динамическое значение; центр плашки над точкой.
        element.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
      }
    },
    dispose: clear,
  };
};
