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

  if (!waiting) return null;

  return (
    <div className="animate-rise safe-bottom fixed inset-x-[var(--s-5)] bottom-[var(--s-6)] z-40 mx-auto flex max-w-[420px] items-center gap-[var(--s-5)] rounded-[var(--radius-md)] border border-border-strong bg-surface-raised px-[var(--s-5)] py-[var(--s-4)] shadow-[var(--shadow-2)]">
      <p className="min-w-0 flex-1 text-sm">Доступна новая версия портала</p>
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
