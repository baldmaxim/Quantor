import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Клиент API живёт в монорепозитории как TypeScript-исходник и собирается вместе с приложением.
  transpilePackages: ['@quantor/api-client'],
  typedRoutes: true,
};

export default nextConfig;
