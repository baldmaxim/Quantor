/**
 * Куда вернуть человека после входа.
 *
 * Принимается только путь внутри портала. Полный адрес из параметра — это открытая
 * переадресация: ссылка «войти в Quantor» уводила бы после входа на чужой сайт.
 * Путь `//host` браузер тоже читает как адрес другого сайта.
 */

export const DEFAULT_NEXT = '/projects';

export const safeNextPath = (raw: string | string[] | null | undefined): string => {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return DEFAULT_NEXT;
  }
  return value;
};
