import { DEFAULT_API_BASE_URL } from '@quantor/api-client/runtime';
import { z } from 'zod';

/**
 * Окружение фронтенда проверяется один раз при загрузке модуля: неверный адрес API должен
 * ломаться сразу и понятно, а не превращаться в загадочные сетевые ошибки в рантайме.
 * Значение по умолчанию задаёт пакет клиента — чтобы адрес не разъезжался в двух местах.
 */
const schema = z.object({
  apiBaseUrl: z.url({ error: 'NEXT_PUBLIC_API_BASE_URL должен быть корректным URL' }),
  apiInternalBaseUrl: z.url({ error: 'API_INTERNAL_BASE_URL должен быть корректным URL' }),
});

const publicApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

export const env = schema.parse({
  apiBaseUrl: publicApiBaseUrl,
  // Адрес API для запросов с сервера портала. Отличается от браузерного в контейнерах,
  // где имя сервиса недоступно снаружи. Локально совпадают, поэтому переменная
  // необязательна.
  apiInternalBaseUrl: process.env.API_INTERNAL_BASE_URL?.trim() || publicApiBaseUrl,
});
