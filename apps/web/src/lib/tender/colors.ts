import { systemColorToken } from './systems';

/** Цвета слоя «Расчёты» по токенам темы: система -> `--tender-sys-*`, выделение и подложка подписей. */
export interface ITenderColors {
  readonly colorOf: (system: string) => string;
  readonly accent: string;
  readonly halo: string;
}

const FALLBACK = 'gray';

export const readTenderColors = (): ITenderColors => {
  if (typeof document === 'undefined') {
    return { colorOf: () => FALLBACK, accent: FALLBACK, halo: FALLBACK };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK;
  const cache = new Map<string, string>();
  return {
    colorOf: (system) => {
      const known = cache.get(system);
      if (known !== undefined) return known;
      const value = token(systemColorToken(system));
      cache.set(system, value);
      return value;
    },
    accent: token('--accent'),
    halo: token('--surface'),
  };
};
