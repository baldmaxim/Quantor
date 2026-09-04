import { DEFAULT_API_BASE_URL } from '@quantor/api-client/runtime';
import { z } from 'zod';

/**
 * Окружение фронтенда проверяется один раз при загрузке модуля: неверный адрес API должен
 * ломаться сразу и понятно, а не превращаться в загадочные сетевые ошибки в рантайме.
 * Значение по умолчанию задаёт пакет клиента — чтобы адрес не разъезжался в двух местах.
 */
const schema = z.object({
  apiBaseUrl: z.url({ error: 'NEXT_PUBLIC_API_BASE_URL должен быть корректным URL' }),
});

export const env = schema.parse({
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL,
});
