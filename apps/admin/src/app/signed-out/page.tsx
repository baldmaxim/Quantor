import type { Metadata } from 'next';

import { env } from '@/lib/env';

/**
 * Требуется вход.
 *
 * Без оболочки и без единого запроса к данным: тому, кто не вошёл, здесь нечего
 * показывать, а пустая навигация создавала бы впечатление, что доступ есть.
 */

export const metadata: Metadata = { title: 'Вход — Управление платформой' };

const SignedOutPage = () => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)]">
    <div className="flex max-w-[420px] flex-col items-center gap-[var(--s-5)] text-center">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Требуется вход</h1>
      <p className="text-sm text-muted">
        Контур управления платформой доступен только администраторам. Войдите, чтобы продолжить.
      </p>
      <a
        href={`${env.apiBaseUrl}/api/v1/auth/login`}
        className="press inline-flex h-[var(--h-ctl)] items-center justify-center rounded-[var(--radius-sm)] border border-accent bg-accent px-[var(--s-6)] text-sm font-medium text-accent-contrast"
      >
        Войти
      </a>
    </div>
  </main>
);

export default SignedOutPage;
