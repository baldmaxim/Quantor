'use client';

import autoAnimate from '@formkit/auto-animate';
import { useEffect, useRef, type RefObject } from 'react';

/**
 * Анимация перестроения списка.
 *
 * Единственная библиотека анимаций в проекте и единственное место, где она нужна.
 * Переходы между страницами делает браузер через View Transitions, появление окон —
 * CSS. А вот перестроение списка при поиске и сортировке CSS не умеет: он не знает,
 * куда строка уехала, потому что она просто исчезла из разметки.
 *
 * Библиотека делает ровно это: замеряет положения до и после, анимирует разницу.
 * Длительность взята из токенов движения, при `prefers-reduced-motion` — отключается.
 */

const DURATION_MS = 200;

export const useListAnimation = <T extends HTMLElement>(enabled = true): RefObject<T | null> => {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) return;

    const controller = autoAnimate(element, {
      duration: DURATION_MS,
      easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    });

    return () => controller.disable();
  }, [enabled]);

  return ref;
};
