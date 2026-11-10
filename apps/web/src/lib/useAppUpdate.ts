'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Обнаружение новой версии портала и её применение.
 *
 * Два источника: waiting service worker и версия сборки на сервере (`/build-version`).
 * Второй нужен потому, что sw.js одинаков во всех сборках и браузер новый worker не находит.
 *
 * Обновление не применяется молча: пользователь может в этот момент грузить пакет
 * или заполнять форму, поэтому наружу отдаётся только состояние тоста.
 */

const FIRST_CHECK_MS = 60_000;
const CHECK_INTERVAL_MS = 5 * 60_000;
const MIN_FOCUS_CHECK_GAP_MS = 60_000;
const RELOAD_FALLBACK_MS = 3_000;

/** Метка «ждёт worker без известной версии с сервера». */
const WAITING_TOKEN = 'waiting';

export interface IAppUpdate {
  visible: boolean;
  dismiss: () => void;
  apply: () => void;
}

const fetchServerVersion = async (): Promise<string | null> => {
  const response = await fetch('/build-version', { cache: 'no-store' });
  if (!response.ok) return null;

  const body: unknown = await response.json();
  if (typeof body !== 'object' || body === null || !('version' in body)) return null;

  const { version } = body;
  return typeof version === 'string' && version !== '' ? version : null;
};

export const useAppUpdate = (): IAppUpdate => {
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const [serverVersion, setServerVersion] = useState<string | null>(null);
  const [dismissedToken, setDismissedToken] = useState<string | null>(null);
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null);

  // Регистрация worker'а и слежение за ожидающим. В разработке не регистрируется:
  // кэш перекрывал бы горячую перезагрузку.
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
        if (cancelled) return;
        registrationRef.current = registration;
        watch(registration);
      })
      .catch(() => {
        /* без service worker портал работает так же, просто без офлайн-страницы */
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Сверка версии с сервером: через минуту после открытия, дальше раз в пять минут
  // и при возвращении на вкладку (не чаще раза в минуту).
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    const builtVersion = process.env.NEXT_PUBLIC_BUILD_VERSION;
    if (!builtVersion) return;

    let cancelled = false;
    let lastCheckAt = 0;

    const check = () => {
      lastCheckAt = Date.now();

      void fetchServerVersion()
        .then((version) => {
          if (!cancelled && version !== null && version !== builtVersion) setServerVersion(version);
        })
        .catch(() => {
          /* сеть пропала — проверим в следующий раз */
        });

      void registrationRef.current?.update().catch(() => {
        /* то же: обновление worker'а не критично */
      });
    };

    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      if (Date.now() - lastCheckAt < MIN_FOCUS_CHECK_GAP_MS) return;
      check();
    };

    let intervalId: number | undefined;
    const firstId = window.setTimeout(() => {
      check();
      intervalId = window.setInterval(check, CHECK_INTERVAL_MS);
    }, FIRST_CHECK_MS);

    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      window.clearTimeout(firstId);
      if (intervalId !== undefined) window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  const token = serverVersion ?? (waiting ? WAITING_TOKEN : null);
  const visible = token !== null && dismissedToken !== token;

  const dismiss = useCallback(() => {
    if (token !== null) setDismissedToken(token);
  }, [token]);

  const apply = useCallback(() => {
    if (!waiting) {
      window.location.reload();
      return;
    }

    let reloaded = false;
    const reload = () => {
      if (reloaded) return;
      reloaded = true;
      window.location.reload();
    };

    // Перезагрузка — только когда новый worker стал управляющим: иначе страница
    // откроется под старым кодом и тост появится снова.
    navigator.serviceWorker.addEventListener('controllerchange', reload, { once: true });
    waiting.postMessage('SKIP_WAITING');
    window.setTimeout(reload, RELOAD_FALLBACK_MS);
  }, [waiting]);

  return { visible, dismiss, apply };
};
