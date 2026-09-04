import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Клиент API живёт в монорепозитории как TypeScript-исходник и собирается вместе с приложением.
  transpilePackages: ['@quantor/api-client'],
  // Типизированные маршруты выключены намеренно: половина пунктов навигации ведёт
  // на разделы, которых на этом этапе ещё нет, и их адреса не являются валидными
  // маршрутами. Включить, когда появятся все разделы.
  typedRoutes: false,
};

export default nextConfig;
