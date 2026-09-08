import { DEFAULT_API_BASE_URL } from '@quantor/api-client/runtime';
import { z } from 'zod';

/**
 * Окружение контура управления.
 *
 * Два адреса API, и это не дублирование. Публичный видит браузер; внутренний
 * используют серверные компоненты, и в контейнерах он другой — имя сервиса снаружи
 * недоступно. Локально они совпадают, поэтому вторая переменная необязательна.
 */
const schema = z.object({
  apiBaseUrl: z.url({ error: 'NEXT_PUBLIC_API_BASE_URL должен быть корректным URL' }),
  apiInternalBaseUrl: z.url({ error: 'API_INTERNAL_BASE_URL должен быть корректным URL' }),
  portalUrl: z.url({ error: 'NEXT_PUBLIC_PORTAL_URL должен быть корректным URL' }),
  buildVersion: z.string().min(1),
});

const publicApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

export const env = schema.parse({
  apiBaseUrl: publicApiBaseUrl,
  apiInternalBaseUrl: process.env.API_INTERNAL_BASE_URL?.trim() || publicApiBaseUrl,
  portalUrl: process.env.NEXT_PUBLIC_PORTAL_URL?.trim() || 'http://localhost:3000',
  // Версия сборки самой админки. Берётся на сборке, а не спрашивается у API:
  // это разные приложения, и их версии могут расходиться — как раз это и важно видеть.
  buildVersion: process.env.NEXT_PUBLIC_BUILD_VERSION?.trim() || 'dev',
});
