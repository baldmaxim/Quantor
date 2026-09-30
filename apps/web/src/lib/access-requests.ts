import { listAdminUsers } from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Сколько заявок на доступ ждёт решения — для администратора платформы в портале.
 *
 * Администратор работает в портале, а заявки разбирает в контуре управления. Почты портал
 * не рассылает, и без отметки здесь о новой заявке узнали бы, только зайдя в админку.
 * Запрос уходит только тому, у кого есть право `system.admin`: остальным API ответил бы отказом.
 * Обновляется как сеанс — при возврате на вкладку, без опроса по таймеру.
 */
export const usePendingAccessRequests = (enabled: boolean) =>
  useQuery({
    queryKey: ['access-requests', 'pending'],
    queryFn: async () =>
      unwrap(
        await listAdminUsers({
          query: { status: 'pending', limit: 1, offset: 0 },
          throwOnError: true,
        }),
      ).total,
    enabled,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
