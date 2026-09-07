import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

/**
 * jsdom не реализует matchMedia, а портал спрашивает его о prefers-reduced-motion
 * и о теме. Заглушка отвечает «предпочтений нет» — это состояние по умолчанию
 * у большинства пользователей, и именно в нём тесты должны видеть обычный интерфейс.
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    media: query,
    matches: false,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

/**
 * Web Animations API в jsdom тоже нет, а библиотека анимации списка вызывает
 * element.animate сразу при подключении.
 */
if (!Element.prototype.animate) {
  Element.prototype.animate = vi.fn(() => ({
    cancel: () => undefined,
    finish: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof Element.prototype.animate;
}

/**
 * ResizeObserver в jsdom тоже нет, а просмотрщик подписывается на изменение размера
 * области, чтобы вписать лист. Заглушка ничего не наблюдает: размеры в jsdom всё равно
 * нулевые, а проверяются здесь жесты, а не раскладка.
 */
if (!('ResizeObserver' in globalThis)) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  } as unknown as typeof ResizeObserver;
}

/**
 * Захват указателя в jsdom не реализован, а просмотрщик берёт его на время
 * перетаскивания — без этого жест теряется, стоит курсору выйти за холст.
 */
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => undefined;
  Element.prototype.releasePointerCapture = () => undefined;
  Element.prototype.hasPointerCapture = () => false;
}

afterEach(() => {
  cleanup();
});
