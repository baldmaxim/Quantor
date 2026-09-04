'use client';

import { readMeta } from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';

import { env } from '@/lib/env';

/**
 * Проверка связи с бэкендом на этапе фундамента: показывает версию контракта и окружение.
 * Полноценная оболочка и состояния загрузки появятся вместе с дизайн-системой.
 */
export const ApiStatus = () => {
  const { data, isPending, isError } = useQuery({
    queryKey: ['meta'],
    queryFn: async () => {
      const response = await readMeta({ throwOnError: true });
      return response.data;
    },
  });

  if (isPending) {
    return (
      <p className="text-sm text-muted" role="status">
        Проверяем связь с API…
      </p>
    );
  }

  if (isError || !data) {
    return (
      <p className="text-sm text-danger" role="status">
        API недоступен по адресу {env.apiBaseUrl}. Запустите бэкенд: <code>pnpm dev</code>.
      </p>
    );
  }

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
      <dt className="text-muted">Контракт API</dt>
      <dd className="font-mono">{data.api_version}</dd>
      <dt className="text-muted">Схема данных</dt>
      <dd className="font-mono">{data.schema_version}</dd>
      <dt className="text-muted">Окружение</dt>
      <dd className="font-mono">{data.environment}</dd>
      <dt className="text-muted">Этап</dt>
      <dd className="font-mono">{data.stage}</dd>
    </dl>
  );
};
