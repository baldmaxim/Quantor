'use client';

/**
 * Переключение темы.
 *
 * Значение хранится в localStorage и применяется к <html>. Тот же ключ читает
 * предзагрузочный скрипт, поэтому после перезагрузки тема не мигает.
 */

import { useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark';

/** Событие смены темы: на него подписан хук, чтобы обойтись без состояния в эффекте. */
const THEME_EVENT = 'quantor:theme';

const STORAGE_KEY = 'quantor-theme';

const THEME_COLORS: Record<Theme, string> = {
  light: '#f1f4f7',
  dark: '#0f1216',
};

export const readTheme = (): Theme => {
  if (typeof document === 'undefined') return 'light';

  const attribute = document.documentElement.getAttribute('data-theme');
  if (attribute === 'dark' || attribute === 'light') return attribute;

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export const applyTheme = (theme: Theme): void => {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  root.style.colorScheme = theme;

  // Шапка установленного приложения красится этим тегом: без синхронизации
  // она останется от прежней темы.
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme]);

  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* приватный режим — тема продержится до конца сессии */
  }

  window.dispatchEvent(new Event(THEME_EVENT));
};

const subscribe = (onChange: () => void): (() => void) => {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
};

/**
 * Текущая тема как внешнее состояние.
 *
 * Тема живёт в атрибуте <html>, а не в React: её ставит предзагрузочный скрипт ещё
 * до гидратации. Поэтому читаем её через useSyncExternalStore — иначе пришлось бы
 * синхронизировать состояние эффектом и получить лишний каскад отрисовок.
 */
export const useTheme = (): Theme => useSyncExternalStore(subscribe, readTheme, () => 'light');

export const toggleTheme = (): Theme => {
  const next: Theme = readTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  return next;
};
