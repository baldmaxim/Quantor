import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';

import { AuthLayout } from '@/components/auth/AuthLayout';
import { ChangePasswordForm } from '@/components/auth/ChangePasswordForm';
import { safeNextPath } from '@/lib/safe-next';
import { fetchServerSession } from '@/lib/server-session';

/**
 * Смена пароля.
 *
 * Вне оболочки портала намеренно: при пароле, выданном администратором, оболочка
 * отправляет сюда, и будь страница внутри неё, переадресация зациклилась бы.
 */

export const metadata: Metadata = {
  title: 'Смена пароля — Quantor',
};

interface IChangePasswordPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const ChangePasswordPage = async ({ searchParams }: IChangePasswordPageProps) => {
  const next = safeNextPath((await searchParams).next);
  const session = await fetchServerSession();

  if (session !== null && !session.authenticated) {
    redirect(`/signed-out?next=${encodeURIComponent('/account/password')}`);
  }
  if (session && session.auth_mode !== 'local') redirect(next);

  const forced = session?.must_change_password ?? false;

  return (
    <AuthLayout
      title="Смена пароля"
      description={
        forced
          ? 'Пароль выдан администратором. Задайте свой, чтобы продолжить работу.'
          : 'После смены пароля другие ваши сеансы завершатся.'
      }
    >
      <ChangePasswordForm next={next} />
      {!forced && (
        <Link
          href={next}
          className="text-center text-sm text-muted underline underline-offset-4 hover:text-text"
        >
          Вернуться без смены
        </Link>
      )}
    </AuthLayout>
  );
};

export default ChangePasswordPage;
