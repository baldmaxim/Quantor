import type { CreateClientConfig } from './src/client.gen';

/**
 * Адрес API по умолчанию — локальный бэкенд из docker-compose.
 * При запуске с другого компьютера задайте NEXT_PUBLIC_API_BASE_URL с IP хоста.
 */
export const DEFAULT_API_BASE_URL = 'http://localhost:8000';

export const resolveApiBaseUrl = (): string =>
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

/** Вызывается сгенерированным клиентом при инициализации. */
export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: resolveApiBaseUrl(),
  // Cookie сеанса обязана уходить вместе с запросом. API живёт на другом origin
  // (:8000 против :3000), а fetch по умолчанию чужие cookie не отправляет — без этой
  // строки аутентификация «не работает», не выдавая при этом ни одной ошибки.
  credentials: 'include',
});
