import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { AuthLayout } from '@/components/auth/AuthLayout';
import { OAuthConsent } from '@/components/auth/OAuthConsent';
import { fetchServerSession } from '@/lib/server-session';

/**
 * Согласие на вход ИИ-чата по OAuth (ADR-0054): сюда чат (Claude, ChatGPT) ведёт человека.
 *
 * Без оболочки портала. Не вошёл — сначала вход, с возвратом сюда же со всеми параметрами
 * чата. Что за чат и что он просит, проверяет API; страница показывает это и передаёт решение.
 */

export const metadata: Metadata = {
  title: 'Доступ для ИИ-чата — Quantor',
};

interface IOAuthAuthorizePageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const OAuthAuthorizePage = async ({ searchParams }: IOAuthAuthorizePageProps) => {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) {
      query.append(key, item);
    }
  }
  const here = `/oauth/authorize?${query.toString()}`;
  const session = await fetchServerSession();

  if (session !== null && !session.authenticated) {
    redirect(`/signed-out?next=${encodeURIComponent(here)}`);
  }
  if (session?.must_change_password) {
    redirect(`/account/password?next=${encodeURIComponent(here)}`);
  }

  return (
    <AuthLayout
      title="Доступ для ИИ-чата"
      description="Чат просит работать с порталом от вашего имени."
    >
      <OAuthConsent query={query.toString()} />
    </AuthLayout>
  );
};

export default OAuthAuthorizePage;
