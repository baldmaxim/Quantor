import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@quantor/api-client', '@quantor/ui'],
  // Типизированные маршруты выключены как и в портале: часть разделов ещё пуста.
  typedRoutes: false,
};

export default nextConfig;
