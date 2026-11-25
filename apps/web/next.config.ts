import path from 'node:path';

import type { NextConfig } from 'next';

// Боевой образ собирается автономным сервером: в контейнер уходит только то, что трассировка
// нашла нужным, без всего дерева node_modules монорепозитория. Локально и в CI сборка
// обычная — `next start` с автономным выводом лишь предупреждает, но путает.
const standalone =
  process.env.QUANTOR_STANDALONE === '1'
    ? {
        output: 'standalone' as const,
        // Корень трассировки — монорепозиторий: иначе пакеты `packages/*` не попадут в образ.
        outputFileTracingRoot: path.resolve(process.cwd(), '../..'),
      }
    : {};

const nextConfig: NextConfig = {
  ...standalone,
  reactStrictMode: true,
  // Клиент API живёт в монорепозитории как TypeScript-исходник и собирается вместе с приложением.
  transpilePackages: ['@quantor/api-client', '@quantor/ui'],
  // Типизированные маршруты выключены намеренно: половина пунктов навигации ведёт
  // на разделы, которых на этом этапе ещё нет, и их адреса не являются валидными
  // маршрутами. Включить, когда появятся все разделы.
  typedRoutes: false,
  // Вход ИИ-чатов по OAuth (ADR-0054): метаданные по адресам RFC 8414 и RFC 9728 отдаёт API,
  // страница лишь пересылает их (`app/oauth/metadata`).
  rewrites: async () => [
    {
      source: '/.well-known/oauth-authorization-server',
      destination: '/oauth/metadata/authorization-server',
    },
    {
      source: '/.well-known/oauth-protected-resource',
      destination: '/oauth/metadata/protected-resource',
    },
    {
      source: '/.well-known/oauth-protected-resource/:path*',
      destination: '/oauth/metadata/protected-resource',
    },
  ],
};

export default nextConfig;
