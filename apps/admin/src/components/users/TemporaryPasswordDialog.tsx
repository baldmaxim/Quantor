'use client';

import type { AdminUserRead } from '@quantor/api-client';
import { Button, Dialog, DialogActions } from '@quantor/ui';
import { useState } from 'react';

import { generatePassword } from '@/lib/password';
import { useSetUserPassword } from '@/lib/queries';
import { failureText } from '@/lib/users';

/**
 * Временный пароль.
 *
 * Почты портал не рассылает, поэтому пароль передаёт сам администратор. Пользователь
 * обязан сменить его при входе, а все его текущие сеансы гаснут сразу после выдачи.
 * Пароль виден только в этом окне: сервер его не возвращает, журнал хранит лишь факт.
 */

interface ITemporaryPasswordDialogProps {
  user: AdminUserRead | null;
  onClose: () => void;
}

export const TemporaryPasswordDialog = ({ user, onClose }: ITemporaryPasswordDialogProps) => {
  const save = useSetUserPassword();
  const [password, setPassword] = useState(generatePassword);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      // Буфер обмена недоступен (нет HTTPS или разрешения) — пароль остаётся на экране.
      setCopied(false);
    }
  };

  return (
    <Dialog
      open={user !== null}
      onClose={onClose}
      busy={save.isPending}
      title="Временный пароль"
      description={user ? `${user.display_name ?? ''} · ${user.email ?? ''}` : undefined}
      onExited={() => {
        setPassword(generatePassword());
        setCopied(false);
        save.reset();
      }}
      footer={
        <DialogActions>
          {save.isSuccess ? (
            <Button variant="primary" onClick={onClose}>
              Готово
            </Button>
          ) : (
            <>
              <Button onClick={onClose} disabled={save.isPending}>
                Отмена
              </Button>
              <Button
                variant="primary"
                disabled={password.length < 10}
                loading={save.isPending}
                loadingLabel="Выдаём…"
                onClick={() => user && save.mutate({ userId: user.id, password })}
              >
                Выдать пароль
              </Button>
            </>
          )}
        </DialogActions>
      }
    >
      <div className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Пароль</span>
        <div className="flex gap-[var(--s-3)]">
          <input
            value={password}
            readOnly={save.isSuccess}
            onChange={(event) => setPassword(event.target.value)}
            spellCheck={false}
            autoComplete="off"
            className="mono h-[44px] min-w-0 flex-1 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-sm text-text lg:h-[var(--h-ctl)]"
          />
          <Button onClick={() => void copy()}>{copied ? 'Скопирован' : 'Скопировать'}</Button>
          {!save.isSuccess && (
            <Button onClick={() => setPassword(generatePassword())}>Другой</Button>
          )}
        </div>
      </div>

      {save.isSuccess ? (
        <p className="text-sm">
          Пароль выдан. Передайте его пользователю лично — при входе портал попросит сменить его.
        </p>
      ) : (
        <p className="text-xs text-muted">
          Прежний пароль перестанет действовать, открытые сеансы пользователя завершатся.
        </p>
      )}

      {save.isError && <p className="text-xs text-danger">{failureText(save.error)}</p>}
    </Dialog>
  );
};
