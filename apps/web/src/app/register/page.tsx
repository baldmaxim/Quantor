import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { AuthLayout } from '@/components/auth/AuthLayout';
import { RegisterForm } from '@/components/auth/RegisterForm';
import { fetchServerSession } from '@/lib/server-session';

/**
 * Заявка на доступ (ADR-0031).
 *
 * Есть только при локальном входе: при внешнем провайдере учётные записи заводятся там,
 * и форма здесь обещала бы то, чего портал не делает.
 */

export const metadata: Metadata = {
  title: 'Заявка на доступ — Quantor',
};

const RegisterPage = async () => {
  const session = await fetchServerSession();

  if (session?.authenticated) redirect('/projects');
  if (session && session.auth_mode !== 'local') redirect('/signed-out');

  return (
    <AuthLayout
      title="Заявка на доступ"
      description="Администратор рассмотрит заявку и назначит рабочее пространство."
    >
      <RegisterForm />
    </AuthLayout>
  );
};

export default RegisterPage;
