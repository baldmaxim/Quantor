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

afterEach(() => {
  cleanup();
});
