/**
 * Service worker портала.
 *
 * Осознанно минимальный. Quantor без сервера бесполезен: проекты, документы и
 * задания живут на API, и делать вид, что портал работает офлайн, — обманывать.
 * Поэтому:
 *
 *   - /api/ не кэшируется никогда. Показанный из кэша статус импорта хуже,
 *     чем честная ошибка сети;
 *   - кэшируется только /_next/static/ — файлы с хешем в имени, они неизменяемы
 *     и устареть не могут;
 *   - навигация идёт в сеть, а без сети отдаётся страница «нет связи».
 *
 * Обновление — по запросу: новый worker ждёт, пока страница не пришлёт SKIP_WAITING.
 * Молчаливый skipWaiting посреди загрузки файлов подменил бы код под работающей сессией.
 */

const VERSION = 'quantor-v1';
const STATIC_CACHE = `${VERSION}-static`;
const SHELL_CACHE = `${VERSION}-shell`;
const OFFLINE_URL = '/offline';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll([OFFLINE_URL])));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => !name.startsWith(VERSION)).map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') void self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  // Хешированная статика: имя меняется вместе с содержимым, поэтому кэш вечен.
  if (url.pathname.startsWith('/_next/static/')) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const hit = await cache.match(request);
        if (hit) return hit;

        const response = await fetch(request);
        if (response.ok) void cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const cache = await caches.open(SHELL_CACHE);
        return (await cache.match(OFFLINE_URL)) ?? Response.error();
      }),
    );
  }
});
