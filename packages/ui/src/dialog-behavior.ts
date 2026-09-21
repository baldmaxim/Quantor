/**
 * Поведение модального окна отдельно от его разметки.
 *
 * Вынесено ради проверяемости: ловушку фокуса и момент размонтирования удобнее
 * проверять на чистых функциях, чем через отрисованное дерево, а компонент
 * остаётся про раскладку.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Длительность из токена движения.
 *
 * Число в TypeScript разъехалось бы с CSS при первой же правке темпа, поэтому
 * читаем то же значение, что использует анимация. Пусто (сборка без стилей,
 * jsdom) или выключенное движение — ноль: окно закрывается сразу.
 */
export const motionMs = (token: string): number => {
  if (typeof window === 'undefined') return 0;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 0;

  const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  if (raw.endsWith('ms')) return Number.parseFloat(raw);
  if (raw.endsWith('s')) return Number.parseFloat(raw) * 1000;
  return 0;
};

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Фокусируемые узлы окна в порядке обхода, без скрытых. */
export const tabbablesOf = (root: HTMLElement): HTMLElement[] =>
  Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (node) => node.offsetParent !== null || node === document.activeElement,
  );

/**
 * Замыкает обход клавишей Tab внутри окна.
 *
 * Нужен вдобавок к `inert` на фоне: атрибут понимают не все браузеры, а
 * программная проверка обхода в тестах его и вовсе не учитывает.
 */
export const trapTab = (root: HTMLElement, event: KeyboardEvent): void => {
  if (event.key !== 'Tab') return;

  const nodes = tabbablesOf(root);
  if (nodes.length === 0) {
    event.preventDefault();
    root.focus();
    return;
  }

  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (first === undefined || last === undefined) return;

  const active = document.activeElement;

  if (event.shiftKey && (active === first || active === root)) {
    event.preventDefault();
    last.focus();
    return;
  }

  if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
};

/** Оверлеи средств разработки Next: пометив их, мы сделали бы экран ошибки мёртвым. */
const DEV_OVERLAY = 'nextjs-portal, [data-nextjs-dialog-overlay], [data-nextjs-toast]';

/**
 * Прячет фон от программ чтения с экрана и от указателя, пока окно открыто.
 *
 * Возвращает откат, снимающий атрибут только с тех узлов, которым его поставили:
 * чужой `inert` не наш, и трогать его нельзя.
 */
export const isolateBackground = (except: HTMLElement): (() => void) => {
  const marked: HTMLElement[] = [];

  for (const node of Array.from(document.body.children)) {
    if (!(node instanceof HTMLElement)) continue;
    if (node === except || node.contains(except)) continue;
    if (node.hasAttribute('inert')) continue;
    if (node.matches(DEV_OVERLAY)) continue;

    node.setAttribute('inert', '');
    marked.push(node);
  }

  return () => {
    for (const node of marked) node.removeAttribute('inert');
  };
};

export type DialogState = 'open' | 'closed';

/**
 * Держит окно в разметке, пока идёт анимация закрытия.
 *
 * `animationend` не приходит в фоновой вкладке и в среде без стилей, поэтому
 * момент размонтирования задаёт таймер — он срабатывает всегда.
 */
export const usePresence = (
  open: boolean,
  onExited?: () => void,
): { mounted: boolean; state: DialogState } => {
  const [mounted, setMounted] = useState(open);
  const [state, setState] = useState<DialogState>(open ? 'open' : 'closed');
  const timer = useRef<number | null>(null);
  const exited = useRef(onExited);
  exited.current = onExited;

  useEffect(() => {
    if (timer.current !== null) {
      // Окно могли открыть заново, пока оно ещё уходило: закрытие отменяется,
      // иначе через мгновение оно исчезнет уже открытым.
      window.clearTimeout(timer.current);
      timer.current = null;
    }

    if (open) {
      setMounted(true);
      setState('open');
      return;
    }

    setState('closed');
    timer.current = window.setTimeout(
      () => {
        timer.current = null;
        setMounted(false);
        exited.current?.();
      },
      motionMs('--dur-base') + 80,
    );

    return () => {
      if (timer.current === null) return;
      window.clearTimeout(timer.current);
      timer.current = null;
    };
  }, [open]);

  return { mounted, state };
};

/**
 * Последний элемент, имевший фокус вне модального окна.
 *
 * Живёт в модуле, а не в состоянии компонента, по двум причинам. Во-первых,
 * `autoFocus` поля внутри окна срабатывает при монтировании — раньше любого
 * эффекта родителя, — и прочитанный в эффекте `activeElement` оказывается уже
 * внутри окна. Во-вторых, окна портала открываются сменой адреса
 * (`?create=1`), а на этом переходе граница `Suspense` пересоздаёт дерево
 * страницы вместе с окном: всё, что окно помнило в своих `ref`, теряется.
 */
let lastFocusOutside: HTMLElement | null = null;
let trackingFocus = false;

const trackFocusOutsideDialogs = (): void => {
  if (trackingFocus || typeof document === 'undefined') return;
  trackingFocus = true;

  document.addEventListener('focusin', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    // Фокус внутри окна не запоминаем: возвращать нужно туда, откуда пришли.
    if (target.closest('[role="dialog"]')) return;
    lastFocusOutside = target;
  });
};

/**
 * Возврат фокуса на то, откуда окно открыли.
 *
 * Возвращается при размонтировании, а не при закрытии: пока окно уходит, фон
 * ещё помечен `inert`, и фокус на нём не удержится.
 */
export const useReturnFocus = (active: boolean): void => {
  const previous = useRef<HTMLElement | null>(null);

  useEffect(() => {
    trackFocusOutsideDialogs();
    if (!active) return;

    previous.current = lastFocusOutside;

    return () => {
      const node = previous.current;
      // Окно могли открыть прямо по адресу, без нажатия: возвращать фокус
      // некуда, и трогать его тогда не нужно.
      if (node && node !== document.body && document.contains(node)) node.focus();
    };
  }, [active]);
};

/** Escape в фазе захвата: один слушатель на окно вместо копии в каждом. */
export const useEscape = (active: boolean, onEscape: () => void): void => {
  const handler = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') onEscape();
    },
    [onEscape],
  );

  useEffect(() => {
    if (!active) return;

    document.addEventListener('keydown', handler, true);
    return () => document.removeEventListener('keydown', handler, true);
  }, [active, handler]);
};
