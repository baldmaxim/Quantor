'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

/**
 * Серверное состояние живёт только в TanStack Query. QueryClient создаётся внутри компонента,
 * иначе при SSR он окажется общим для всех пользователей.
 */
export const Providers = ({ children }: { children: ReactNode }) => {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
            // Определение «офлайн» по браузеру здесь вредит: портал общается с API,
            // который может работать на этой же машине. Без этого запрос к недоступному
            // серверу навсегда застревает в паузе вместо честной ошибки.
            networkMode: 'always',
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};
