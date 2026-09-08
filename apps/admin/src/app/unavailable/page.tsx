import type { Metadata } from 'next';

/**
 * API не отвечает.
 *
 * Отдельная страница, а не страница входа: недоступность сервера и отсутствие сеанса —
 * разные поломки. Смешать их значит отправить администратора чинить вход, пока лежит API.
 */

export const metadata: Metadata = { title: 'API недоступен — Управление платформой' };

const UnavailablePage = () => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)]">
    <div className="flex max-w-[440px] flex-col items-center gap-[var(--s-5)] text-center">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">API не отвечает</h1>
      <p className="text-sm text-muted">
        Подтвердить права не удалось: сервер не ответил. Это не отказ в доступе — проверьте
        состояние API и обновите страницу.
      </p>
    </div>
  </main>
);

export default UnavailablePage;
