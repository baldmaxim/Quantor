'use client';

import { usePendingUsersCount } from '@/lib/queries';

/**
 * Число заявок, ждущих решения, — рядом с разделом «Пользователи и доступ».
 *
 * Заявку подают без администратора, и узнать о ней иначе, чем зайдя в раздел, нельзя:
 * почты портал не рассылает. Ноль не показывается — пустая отметка только отвлекает.
 */
export const PendingUsersBadge = () => {
  const { data } = usePendingUsersCount();
  if (!data) return null;

  return (
    <span
      aria-label={`Заявок ждёт решения: ${data}`}
      className="ml-auto rounded-full bg-warning-soft px-[var(--s-3)] text-micro font-semibold text-warning"
    >
      {data}
    </span>
  );
};
