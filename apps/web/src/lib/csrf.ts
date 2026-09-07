import { client } from '@quantor/api-client/client';

/**
 * Подтверждение небезопасных запросов.
 *
 * Сервер требует заголовок `X-CSRF-Token`, совпадающий с одноимённой cookie. Cookie
 * читаемая намеренно: чужая страница может заставить браузер отправить её вместе с
 * запросом, но прочитать значение и повторить заголовком — нет.
 *
 * Перехватчик ставится один раз на модуль клиента. Повторная установка добавила бы второй
 * такой же обработчик — безвредно, но бессмысленно.
 */

const CSRF_COOKIE = 'quantor_csrf';
const CSRF_HEADER = 'X-CSRF-Token';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

let installed = false;

const readCookie = (name: string): string | null => {
  const prefix = `${name}=`;
  for (const chunk of document.cookie.split(';')) {
    const trimmed = chunk.trim();
    if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
  }
  return null;
};

export const installCsrfInterceptor = (): void => {
  if (installed || typeof document === 'undefined') return;
  installed = true;

  client.interceptors.request.use((request: Request) => {
    if (!UNSAFE_METHODS.has(request.method.toUpperCase())) return request;

    const token = readCookie(CSRF_COOKIE);
    // Токена нет в dev-режиме — там подтверждение не проверяется. Молча не добавляем
    // пустой заголовок: пустое значение сервер отвергнет как несовпадение.
    if (!token) return request;

    // Заголовки уже созданного запроса менять нельзя, поэтому собирается новый.
    const headers = new Headers(request.headers);
    headers.set(CSRF_HEADER, token);
    return new Request(request, { headers });
  });
};
