'use client';

import type { AdminUserRead } from '@quantor/api-client';
import { Button, Dialog, DialogActions, SegmentedControl } from '@quantor/ui';
import { useState } from 'react';

import {
  useAdminWorkspaces,
  useApproveUser,
  useSetUserMembership,
  type WorkspaceRole,
} from '@/lib/queries';
import { failureText, roleLabel } from '@/lib/users';

/**
 * Выдача доступа: пространство и роль.
 *
 * Одно окно на два случая. Одобрение заявки без пространства не бывает — пользователь
 * без членства вошёл бы в пустой портал с отказом на каждом экране; поэтому решение
 * «пустить» и «куда и с какими правами» принимается одним действием.
 */

const ROLES: readonly WorkspaceRole[] = ['viewer', 'reviewer', 'engineer', 'workspace_admin'];

interface IUserAccessDialogProps {
  user: AdminUserRead | null;
  mode: 'approve' | 'membership';
  onClose: () => void;
}

export const UserAccessDialog = ({ user, mode, onClose }: IUserAccessDialogProps) => {
  const workspaces = useAdminWorkspaces();
  const approve = useApproveUser();
  const membership = useSetUserMembership();
  const action = mode === 'approve' ? approve : membership;

  const [workspaceId, setWorkspaceId] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('engineer');

  const active = (workspaces.data ?? []).filter((item) => item.status === 'active');
  const selected = workspaceId || active[0]?.id || '';

  const submit = () => {
    if (!user || !selected) return;
    action.mutate({ userId: user.id, workspaceId: selected, role }, { onSuccess: onClose });
  };

  return (
    <Dialog
      open={user !== null}
      onClose={onClose}
      busy={action.isPending}
      title={mode === 'approve' ? 'Одобрить заявку' : 'Роль в пространстве'}
      description={user ? `${user.display_name ?? ''} · ${user.email ?? ''}` : undefined}
      onExited={() => {
        setWorkspaceId('');
        setRole('engineer');
        approve.reset();
        membership.reset();
      }}
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={action.isPending}>
            Отмена
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={!selected}
            loading={action.isPending}
            loadingLabel="Сохраняем…"
          >
            {mode === 'approve' ? 'Одобрить' : 'Сохранить'}
          </Button>
        </DialogActions>
      }
    >
      <label className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Рабочее пространство</span>
        <select
          value={selected}
          disabled={action.isPending || workspaces.isPending}
          onChange={(event) => setWorkspaceId(event.target.value)}
          className="h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-sm text-text lg:h-[var(--h-ctl)]"
        >
          {active.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>

      <SegmentedControl
        label="Роль"
        layout="grid"
        value={role}
        onChange={setRole}
        options={ROLES.map((value) => ({ value, label: roleLabel(value) }))}
      />

      {action.isError && <p className="text-xs text-danger">{failureText(action.error)}</p>}
    </Dialog>
  );
};
