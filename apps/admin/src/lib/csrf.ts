import { client } from '@quantor/api-client/client';

/**
 * Подтверждение небезопасных запросов.
 *
 * Тот же двойной токен, что и в портале: сервер требует заголовок, совпадающий с
 * читаемой cookie. Копия здесь, а не общий модуль, потому что модуль клиента API у
 * каждого приложения свой — перехватчик, поставленный в портале, до админки не доедет.
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
    if (!token) return request;

    const headers = new Headers(request.headers);
    headers.set(CSRF_HEADER, token);
    return new Request(request, { headers });
  });
};
