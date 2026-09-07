import { readSession, logout as logoutRequest } from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Состояние сеанса на клиенте.
 *
 * Единственный источник правды — ответ сервера. Права перечислены в нём явно, поэтому
 * интерфейсу не нужно знать состав ролей и повторять его у себя: разошедшаяся копия
 * показывала бы кнопки, на которые API отвечает отказом.
 *
 * Видимость элементов — это удобство, а не граница безопасности. Каждая операция всё равно
 * проверяется на сервере.
 */

export const sessionQueryKey = ['session'] as const;

export const useSession = () =>
  useQuery({
    queryKey: sessionQueryKey,
    queryFn: async () => unwrap(await readSession({ throwOnError: true })),
    // Сеанс меняется редко, но протухнуть может в любой момент; при возврате на вкладку
    // лучше спросить заново, чем рисовать интерфейс отозванных прав.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

/** Есть ли у текущего пользователя право. Неизвестный сеанс прав не даёт. */
export const useHasPermission = (permission: string): boolean => {
  const { data } = useSession();
  return data?.permissions?.includes(permission) ?? false;
};

export const useLogout = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => unwrap(await logoutRequest({ throwOnError: true })),
    onSuccess: () => {
      // Кэш чистится целиком: в нём лежат проекты и документы прежнего пользователя,
      // и показать их следующему было бы утечкой через собственный интерфейс.
      queryClient.clear();
      // Полная перезагрузка, а не переход маршрутизатором: переход сохранил бы состояние
      // React со всем, что уже загружено на экране. Дальше серверная проверка в оболочке
      // портала сама уведёт на страницу входа — отдельный адрес здесь не нужен.
      window.location.reload();
    },
  });
};
