import type { SessionResponse } from '@quantor/api-client';
import { cookies } from 'next/headers';

import { env } from '@/lib/env';

/**
 * Сеанс, прочитанный на сервере до отрисовки.
 *
 * Нужен ровно для одного: портал не должен рисовать оболочку и запрашивать проекты
 * раньше, чем подтверждено, что спрашивающий имеет на них право. Клиентская проверка
 * этого не даёт — разметка уже ушла в браузер, а запросы уже отправлены.
 *
 * Cookie пересылается как есть: сервер портала и API — один site, поэтому cookie сеанса
 * доходит и сюда. Если API окажется на другом регистрируемом домене, потребуется
 * прокси-маршрут внутри приложения (ADR-0013).
 */

const SESSION_PATH = '/api/v1/auth/session';

// Отдельный предел: страница не должна ждать недоступный API дольше, чем человек готов
// смотреть на пустой экран.
const TIMEOUT_MS = 5000;

export type ServerSession = SessionResponse | null;

export const fetchServerSession = async (): Promise<ServerSession> => {
  const cookieHeader = (await cookies()).toString();

  try {
    const response = await fetch(`${env.apiInternalBaseUrl}${SESSION_PATH}`, {
      headers: cookieHeader ? { cookie: cookieHeader } : {},
      // Состояние сеанса не кэшируется никогда: кэш здесь означает показ чужих прав.
      cache: 'no-store',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return (await response.json()) as SessionResponse;
  } catch {
    // Недоступный API — это не «не вошёл». Различает вызывающий: null означает
    // «подтвердить не удалось», и решение принимает страница.
    return null;
  }
};
