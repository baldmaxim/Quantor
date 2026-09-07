import type { SessionResponse } from '@quantor/api-client';
import { cookies } from 'next/headers';

import { env } from '@/lib/env';

/**
 * Сеанс, прочитанный на сервере до отрисовки.
 *
 * Это и есть граница входа в контур управления. Проверка на клиенте её не заменяет:
 * разметка оболочки к тому моменту уже ушла бы в браузер, а запросы за настройками и
 * журналом — на сервер.
 *
 * Cookie пересылается как есть. Сервер админки и API относятся к одному
 * регистрируемому домену, поэтому сеанс доходит и сюда; если API окажется на другом
 * домене, потребуется прокси-маршрут внутри приложения (ADR-0013, пункт 4).
 */

const SESSION_PATH = '/api/v1/auth/session';

// Страница не должна ждать недоступный API дольше, чем человек готов смотреть
// на пустой экран.
const TIMEOUT_MS = 5000;

export type SessionState =
  | { kind: 'authenticated'; session: SessionResponse }
  | { kind: 'anonymous' }
  | { kind: 'api-unreachable' };

export const ADMIN_PERMISSION = 'system.admin';

export const fetchSessionState = async (): Promise<SessionState> => {
  const cookieHeader = (await cookies()).toString();

  try {
    const response = await fetch(`${env.apiInternalBaseUrl}${SESSION_PATH}`, {
      headers: cookieHeader ? { cookie: cookieHeader } : {},
      // Состояние сеанса не кэшируется никогда: кэш здесь означает показ чужих прав.
      cache: 'no-store',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return { kind: 'anonymous' };

    const session = (await response.json()) as SessionResponse;
    return session.authenticated ? { kind: 'authenticated', session } : { kind: 'anonymous' };
  } catch {
    // Недоступный API — это не «не вошёл». Смешивать их нельзя: администратор пришёл бы
    // на страницу входа чинить сеанс, пока лежит сервер.
    return { kind: 'api-unreachable' };
  }
};

export const canOpenConsole = (session: SessionResponse): boolean =>
  session.permissions?.includes(ADMIN_PERMISSION) ?? false;
