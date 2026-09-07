import type { Metadata } from 'next';

/**
 * Страница «нет связи».
 *
 * Отдаётся service worker'ом, когда сеть недоступна. Без интерактива и без запросов:
 * в этот момент выполнить их всё равно нечем.
 */

export const metadata: Metadata = {
  title: 'Нет связи — Quantor',
};

const OfflinePage = () => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)]">
    <div className="flex max-w-[420px] flex-col items-center gap-[var(--s-5)] text-center">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">Нет связи</h1>
      <p className="text-sm text-muted">
        Портал работает с документами на сервере, поэтому без сети открыть проект не получится.
        Проверьте подключение и обновите страницу.
      </p>
    </div>
  </main>
);

export default OfflinePage;
