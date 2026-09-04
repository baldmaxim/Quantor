'use client';

/**
 * Отправка сведений об ошибке клиента.
 *
 * Сейчас это журнал браузера с единым форматом записи, а не внешний сборщик: подключать
 * его до появления эксплуатации значило бы гонять данные проектной документации в чужой
 * сервис без нужды. Точка расширения одна — эта функция.
 *
 * В запись не попадают ни содержимое документов, ни адреса файлов: только тип ошибки,
 * сообщение и место.
 */

export type ErrorScope = 'route' | 'viewer' | 'upload' | 'query';

interface ClientErrorRecord {
  readonly scope: ErrorScope;
  readonly name: string;
  readonly message: string;
  readonly digest?: string;
  readonly path: string;
  readonly at: string;
}

export const reportClientError = (error: unknown, scope: ErrorScope): ClientErrorRecord => {
  const record: ClientErrorRecord = {
    scope,
    name: error instanceof Error ? error.name : 'UnknownError',
    message: error instanceof Error ? error.message : String(error),
    ...(error instanceof Error && 'digest' in error
      ? { digest: String((error as { digest?: unknown }).digest) }
      : {}),
    path: typeof window === 'undefined' ? '' : window.location.pathname,
    at: new Date().toISOString(),
  };

  // Единственная точка вывода ошибок клиента: разбросанные console.error по коду
  // невозможно ни найти, ни заменить на внешний сборщик.
  console.error('[quantor]', record);
  return record;
};
