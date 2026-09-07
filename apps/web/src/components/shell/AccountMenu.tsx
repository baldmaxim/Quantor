'use client';

import { useEffect, useRef, useState } from 'react';

import { cx } from '@/components/ui';
import { useLogout, useSession } from '@/lib/session';

/**
 * Меню учётной записи: кто вошёл, где работает и как выйти.
 *
 * Переключатель пространств показывается только при нескольких членствах: выбор из одного
 * варианта — это не выбор, а лишний элемент, который придётся объяснять.
 *
 * Ссылка на админ-контур появляется только при праве `system.admin`. Это удобство, а не
 * защита: сам контур закрыт серверной проверкой, и прямой переход по адресу ничего не даст.
 */

const ADMIN_PERMISSION = 'system.admin';

export const AccountMenu = ({ compact = false }: { compact?: boolean }) => {
  const { data: session } = useSession();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  // Клик мимо и Escape закрывают меню: иначе оно остаётся висеть поверх работы.
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (!session?.authenticated) return null;

  const label = session.user?.display_name || session.user?.email || 'Учётная запись';
  const initial = label.trim().charAt(0).toUpperCase() || '?';
  const workspaces = session.workspaces ?? [];
  const current = workspaces.find((item) => item.id === session.workspace_id);
  const canOpenAdmin = session.permissions?.includes(ADMIN_PERMISSION) ?? false;

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Учётная запись: ${label}`}
        title={label}
        className={cx(
          'press grid place-items-center rounded-full border border-border-control bg-surface-muted text-xs font-semibold text-text',
          compact ? 'h-[28px] w-[28px]' : 'h-[32px] w-[32px]',
          'hover:border-border-strong',
        )}
      >
        {initial}
      </button>

      {open && (
        <div
          role="menu"
          className={cx(
            'animate-rise absolute z-40 w-[248px] rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-4)] shadow-[var(--shadow-2)]',
            compact
              ? 'right-0 bottom-[calc(100%+var(--s-3))]'
              : 'bottom-0 left-[calc(100%+var(--s-3))]',
          )}
        >
          <div className="mb-[var(--s-4)] flex flex-col gap-[2px]">
            <span className="wrap-anywhere text-sm font-medium">{label}</span>
            {session.user?.email && (
              <span className="wrap-anywhere text-xs text-muted">{session.user.email}</span>
            )}
            {current && (
              <span className="mt-[var(--s-2)] text-xs text-muted">
                {current.name} · {current.role}
              </span>
            )}
          </div>

          {workspaces.length > 1 && (
            <div className="mb-[var(--s-4)] flex flex-col gap-[var(--s-2)] border-t border-border pt-[var(--s-4)]">
              <span className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                Рабочие пространства
              </span>
              {workspaces.map((workspace) => (
                <span
                  key={workspace.id}
                  className={cx(
                    'rounded-[var(--radius-xs)] px-[var(--s-3)] py-[var(--s-2)] text-xs',
                    workspace.id === session.workspace_id
                      ? 'bg-surface-muted text-text'
                      : 'text-muted',
                  )}
                >
                  {workspace.name}
                </span>
              ))}
            </div>
          )}

          {canOpenAdmin && (
            <a
              href="/admin"
              role="menuitem"
              className="press mb-[var(--s-2)] block rounded-[var(--radius-xs)] px-[var(--s-3)] py-[var(--s-3)] text-sm text-muted hover:bg-surface-muted hover:text-text"
            >
              Управление платформой
            </a>
          )}

          <button
            type="button"
            role="menuitem"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            className="press block w-full rounded-[var(--radius-xs)] px-[var(--s-3)] py-[var(--s-3)] text-left text-sm text-danger hover:bg-danger-soft disabled:opacity-45"
          >
            {logout.isPending ? 'Выходим…' : 'Выйти'}
          </button>
        </div>
      )}
    </div>
  );
};
