'use client';

import { useEffect, useState } from 'react';

import { Button } from '@/components/ui';

/**
 * Регистрация service worker и предложение обновиться.
 *
 * Обновление не применяется молча: пользователь может в этот момент грузить
 * пятидесятимегабайтный пакет, и подмена кода под работающей вкладкой оборвала бы
 * загрузку. Поэтому новый worker ждёт, а на экране появляется предложение.
 *
 * В разработке не регистрируется: кэш перекрывал бы горячую перезагрузку.
 */

export const ServiceWorkerBridge = () => {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    if (!('serviceWorker' in navigator)) return;

    let cancelled = false;

    const watch = (registration: ServiceWorkerRegistration) => {
      if (registration.waiting) setWaiting(registration.waiting);

      registration.addEventListener('updatefound', () => {
        const installing = registration.installing;
        if (!installing) return;

        installing.addEventListener('statechange', () => {
          // Установился при уже работающем worker'е — значит, это новая версия.
          if (installing.state === 'installed' && navigator.serviceWorker.controller) {
            setWaiting(installing);
          }
        });
      });
    };

    void navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        if (!cancelled) watch(registration);
      })
      .catch(() => {
        /* без service worker портал работает так же, просто без офлайн-страницы */
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!waiting || dismissed) return null;

  return (
    <div
      role="status"
      // Над нижней навигацией, а не поверх неё: на телефоне разделы прибиты к низу
      // экрана, и тост, лежащий на них, забирает себе нажатия по «Проектам».
      className="animate-rise safe-bottom fixed inset-x-[var(--s-5)] bottom-[calc(var(--h-bottom-nav)+var(--s-5))] z-40 mx-auto flex max-w-[420px] flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface-raised px-[var(--s-5)] py-[var(--s-4)] shadow-[var(--shadow-2)] md:bottom-[var(--s-6)]"
    >
      <p className="min-w-0 flex-1 text-sm">Доступна новая версия портала</p>
      {/* Отложить можно: обновление перезагружает страницу, а пользователь мог
          в этот момент заполнять форму. */}
      <Button onClick={() => setDismissed(true)}>Позже</Button>
      <Button
        variant="primary"
        onClick={() => {
          waiting.postMessage('SKIP_WAITING');
          window.location.reload();
        }}
      >
        Обновить
      </Button>
    </div>
  );
};
