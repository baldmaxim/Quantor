'use client';

import type { AdminUserRead } from '@quantor/api-client';
import { Button, StatusBadge } from '@quantor/ui';

import { isLocked, roleLabel, userState } from '@/lib/users';

/**
 * Таблица пользователей с действиями по строке.
 *
 * Действия зависят от состояния: заявку одобряют или отклоняют, одобренному меняют роль,
 * выдают временный пароль и отключают. Недоступное не показывается вовсе — серая кнопка
 * «Отклонить» у давно работающего сотрудника только сбивала бы с толку.
 */

export interface IUserActions {
  onApprove: (user: AdminUserRead) => void;
  onReject: (user: AdminUserRead) => void;
  onMembership: (user: AdminUserRead) => void;
  onPassword: (user: AdminUserRead) => void;
  onToggleActive: (user: AdminUserRead) => void;
  busyId: string | null;
  selfId: string | null;
}

interface IUsersTableProps extends IUserActions {
  items: readonly AdminUserRead[];
}

const formatDate = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleString('ru-RU') : '—';

const Actions = ({ user, ...actions }: IUserActions & { user: AdminUserRead }) => {
  const busy = actions.busyId === user.id;

  if (user.approval_status !== 'approved') {
    return (
      <div className="flex flex-wrap gap-[var(--s-2)]">
        <Button compact variant="primary" disabled={busy} onClick={() => actions.onApprove(user)}>
          Одобрить
        </Button>
        {user.approval_status === 'pending' && (
          <Button compact disabled={busy} onClick={() => actions.onReject(user)}>
            Отклонить
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-[var(--s-2)]">
      <Button compact disabled={busy} onClick={() => actions.onMembership(user)}>
        Роль
      </Button>
      {user.is_local && (
        <Button compact disabled={busy} onClick={() => actions.onPassword(user)}>
          Пароль
        </Button>
      )}
      {user.id !== actions.selfId && (
        <Button
          compact
          variant={user.is_active ? 'danger' : 'default'}
          loading={busy}
          onClick={() => actions.onToggleActive(user)}
        >
          {user.is_active ? 'Отключить' : 'Включить'}
        </Button>
      )}
    </div>
  );
};

export const UsersTable = ({ items, ...actions }: IUsersTableProps) => (
  <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
    <table className="admin-table">
      <thead>
        <tr>
          <th>Пользователь</th>
          <th>Состояние</th>
          <th>Пространства</th>
          <th>Последний вход</th>
          <th>Действия</th>
        </tr>
      </thead>
      <tbody>
        {items.map((user) => {
          const state = userState(user);
          const memberships = user.memberships ?? [];
          return (
            <tr key={user.id}>
              <td>
                <div className="flex flex-col gap-[2px]">
                  <span className="text-xs wrap-anywhere">{user.display_name ?? '—'}</span>
                  <span className="text-micro text-muted wrap-anywhere">{user.email ?? ''}</span>
                  {user.is_platform_admin && (
                    <span className="text-micro text-accent">администратор платформы</span>
                  )}
                </div>
              </td>
              <td>
                <div className="flex flex-col items-start gap-[var(--s-2)]">
                  <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
                  {isLocked(user) && (
                    <span className="text-micro text-warning">
                      вход заблокирован до {formatDate(user.locked_until)}
                    </span>
                  )}
                  {user.must_change_password && (
                    <span className="text-micro text-muted">сменит пароль при входе</span>
                  )}
                </div>
              </td>
              <td>
                {memberships.length === 0 ? (
                  <span className="text-micro text-muted">—</span>
                ) : (
                  <div className="flex flex-col gap-[2px]">
                    {memberships.map((item) => (
                      <span key={item.id} className="text-xs">
                        {item.name} · <span className="text-muted">{roleLabel(item.role)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </td>
              <td className="mono text-micro whitespace-nowrap">
                {formatDate(user.last_login_at)}
              </td>
              <td>
                <Actions user={user} {...actions} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);
