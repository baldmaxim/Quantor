import type { Metadata } from 'next';

import { env } from '@/lib/env';

/**
 * Отказ в доступе.
 *
 * Оболочка не строится и ни один привилегированный запрос не уходит. Ссылка ведёт
 * обратно в портал: человек вошёл, просто не сюда.
 */

export const metadata: Metadata = { title: 'Доступ запрещён — Управление платформой' };

const ForbiddenPage = () => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)]">
    <div className="flex max-w-[440px] flex-col items-center gap-[var(--s-5)] text-center">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Доступ запрещён</h1>
      <p className="text-sm text-muted">
        Управление платформой доступно только с правом <span className="mono">system.admin</span>.
        Если оно должно у вас быть — обратитесь к администратору установки.
      </p>
      <a
        href={env.portalUrl}
        className="press inline-flex h-[var(--h-ctl)] items-center justify-center rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-6)] text-sm"
      >
        Вернуться в портал
      </a>
    </div>
  </main>
);

export default ForbiddenPage;
