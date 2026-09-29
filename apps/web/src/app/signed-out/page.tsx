import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { buttonClassName } from '@quantor/ui';

import { AuthLayout } from '@/components/auth/AuthLayout';
import { SignInForm } from '@/components/auth/SignInForm';
import { env } from '@/lib/env';
import { safeNextPath } from '@/lib/safe-next';
import { fetchServerSession } from '@/lib/server-session';

/**
 * Страница входа.
 *
 * Без оболочки портала и без единого запроса к данным: тому, кто не вошёл, нечего здесь
 * показывать. Способ входа выбирает сервер (`auth_mode`): при локальном входе — форма
 * почты и пароля (ADR-0031), при внешнем провайдере — переход на сервер API, потому что
 * только он знает адрес провайдера и умеет обменять код на сеанс.
 */

export const metadata: Metadata = {
  title: 'Вход — Quantor',
};

interface ISignedOutPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const SignedOutPage = async ({ searchParams }: ISignedOutPageProps) => {
  const next = safeNextPath((await searchParams).next);
  const session = await fetchServerSession();

  if (session?.authenticated) redirect(next);

  // Недоступный API — не повод прятать форму: попытка входа сама честно скажет,
  // что сервер не отвечает.
  if ((session?.auth_mode ?? 'local') === 'local') {
    return (
      <AuthLayout
        title="Вход в портал"
        description="Проекты и документы доступны участникам рабочих пространств."
      >
        <SignInForm next={next} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Требуется вход"
      description="Проекты и документы доступны только участникам рабочего пространства. Войдите, чтобы продолжить."
    >
      {/* Обычная ссылка, а не next/link: вход уходит на сервер API, и переход
          обязан быть полным, с отдачей cookie. */}
      <a
        href={`${env.apiBaseUrl}/api/v1/auth/login?next=${encodeURIComponent(next)}`}
        className={buttonClassName({ variant: 'primary' })}
      >
        Войти
      </a>
    </AuthLayout>
  );
};

export default SignedOutPage;
