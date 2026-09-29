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
  transpilePackages: ['@quantor/api-client', '@quantor/ui'],
  // Типизированные маршруты выключены как и в портале: часть разделов ещё пуста.
  typedRoutes: false,
};

export default nextConfig;
