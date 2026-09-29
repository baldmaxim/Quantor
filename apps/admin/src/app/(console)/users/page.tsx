'use client';

import type { AdminUserRead, ApprovalStatus } from '@quantor/api-client';
import { Button, EmptyState, ErrorState, SegmentedControl, SkeletonRows } from '@quantor/ui';
import { useState } from 'react';

import { Section } from '@/components/common/Section';
import { TemporaryPasswordDialog } from '@/components/users/TemporaryPasswordDialog';
import { UserAccessDialog } from '@/components/users/UserAccessDialog';
import { UsersTable } from '@/components/users/UsersTable';
import { useAdminUsers, useRejectUser, useSession, useSetUserActive } from '@/lib/queries';
import { failureText } from '@/lib/users';

/**
 * Пользователи и доступ (ADR-0031).
 *
 * Очередь заявок открывается первой: это то, ради чего сюда приходят. Решение по заявке
 * сразу выдаёт пространство и роль. Все изменения пишутся в журнал сервером.
 */

const PAGE_SIZE = 50;

type Filter = ApprovalStatus | 'all';

const FILTERS: readonly { value: Filter; label: string }[] = [
  { value: 'pending', label: 'Заявки' },
  { value: 'approved', label: 'Одобренные' },
  { value: 'rejected', label: 'Отклонённые' },
  { value: 'all', label: 'Все' },
];

const EMPTY: Record<Filter, string> = {
  pending: 'Новых заявок нет. Заявку подают со страницы входа портала.',
  approved: 'Одобренных пользователей пока нет.',
  rejected: 'Отклонённых заявок нет.',
  all: 'Пользователей пока нет.',
};

const Page = () => {
  const [filter, setFilter] = useState<Filter>('pending');
  const [offset, setOffset] = useState(0);
  const [access, setAccess] = useState<{
    user: AdminUserRead;
    mode: 'approve' | 'membership';
  } | null>(null);
  const [passwordFor, setPasswordFor] = useState<AdminUserRead | null>(null);

  const session = useSession();
  const users = useAdminUsers({
    limit: PAGE_SIZE,
    offset,
    ...(filter === 'all' ? {} : { status: filter }),
  });
  const reject = useRejectUser();
  const toggle = useSetUserActive();

  const busyId =
    (reject.isPending ? reject.variables : null) ??
    (toggle.isPending ? toggle.variables?.userId : null) ??
    null;
  const failure = reject.isError ? reject.error : toggle.isError ? toggle.error : null;

  const content = () => {
    if (users.isPending) return <SkeletonRows rows={6} />;
    if (users.isError) {
      return (
        <ErrorState
          title="Список не загрузился"
          onRetry={() => void users.refetch()}
          description="Проверьте, что API отвечает."
        />
      );
    }

    const { items, total } = users.data;
    if (items.length === 0) return <EmptyState title="Пусто" description={EMPTY[filter]} />;

    const shown = offset + items.length;
    return (
      <>
        <UsersTable
          items={items}
          busyId={busyId}
          selfId={session.data?.user?.id ?? null}
          onApprove={(user) => setAccess({ user, mode: 'approve' })}
          onMembership={(user) => setAccess({ user, mode: 'membership' })}
          onReject={(user) => reject.mutate(user.id)}
          onPassword={setPasswordFor}
          onToggleActive={(user) => toggle.mutate({ userId: user.id, active: !user.is_active })}
        />
        <div className="flex flex-wrap items-center justify-between gap-[var(--s-4)]">
          <span className="text-xs text-muted">
            показано {offset + 1}–{shown} из {total}
          </span>
          <div className="flex gap-[var(--s-3)]">
            <Button
              compact
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Назад
            </Button>
            <Button compact disabled={shown >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Дальше
            </Button>
          </div>
        </div>
      </>
    );
  };

  return (
    <Section
      title="Пользователи и доступ"
      description="Заявки на доступ, роли в пространствах, временные пароли. Отключение сразу завершает все сеансы пользователя."
    >
      <SegmentedControl
        label="Показать"
        layout="wrap"
        value={filter}
        onChange={(value) => {
          setFilter(value);
          setOffset(0);
        }}
        options={FILTERS}
      />

      {failure && <p className="text-xs text-danger">{failureText(failure)}</p>}

      {content()}

      <UserAccessDialog
        user={access?.user ?? null}
        mode={access?.mode ?? 'approve'}
        onClose={() => setAccess(null)}
      />
      <TemporaryPasswordDialog user={passwordFor} onClose={() => setPasswordFor(null)} />
    </Section>
  );
};

export default Page;
