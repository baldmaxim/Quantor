'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { installCsrfInterceptor } from '@/lib/csrf';

/**
 * Общее состояние контура управления.
 *
 * Отказ 401 или 403 посреди работы означает, что права отозвали, — тогда страница
 * перезагружается, и серверная проверка в оболочке уводит куда следует. Клиентская
 * реакция здесь для удобства; границей остаётся сервер.
 */
export const Providers = ({ children }: { children: ReactNode }) => {
  useState(() => {
    installCsrfInterceptor();
    return null;
  });

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: 1,
            // Диагностику не опрашиваем сами: обновление — по кнопке. Автоматический
            // опрос страницы состояния добавляет нагрузку ровно тогда, когда система
            // и так нездорова.
            refetchInterval: false,
            refetchOnWindowFocus: false,
            networkMode: 'always',
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};
