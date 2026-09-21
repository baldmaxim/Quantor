import type { Metadata } from 'next';

import { buttonClassName } from '@quantor/ui';

import { env } from '@/lib/env';

/**
 * Страница «требуется вход».
 *
 * Без оболочки портала и без единого запроса к данным: тому, кто не вошёл, нечего здесь
 * показывать, а пустая рейка разделов создавала бы впечатление, что доступ есть.
 *
 * Кнопка ведёт прямо в API: поток входа начинается на сервере, потому что только он знает
 * адрес провайдера и умеет обменять код на сеанс.
 */

export const metadata: Metadata = {
  title: 'Вход — Quantor',
};

const SignedOutPage = () => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)]">
    <div className="flex max-w-[420px] flex-col items-center gap-[var(--s-5)] text-center">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Требуется вход</h1>
      <p className="text-sm text-muted">
        Проекты и документы доступны только участникам рабочего пространства. Войдите, чтобы
        продолжить.
      </p>
      {/* Обычная ссылка, а не next/link: вход уходит на сервер API, и переход
          обязан быть полным, с отдачей cookie. */}
      <a
        href={`${env.apiBaseUrl}/api/v1/auth/login?next=/projects`}
        className={buttonClassName({ variant: 'primary' })}
      >
        Войти
      </a>
    </div>
  </main>
);

export default SignedOutPage;
