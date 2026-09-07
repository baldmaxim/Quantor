import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';
import { Providers } from './providers';
import { ServiceWorkerBridge } from './service-worker';
import { ThemeScript } from './theme-script';

export const metadata: Metadata = {
  title: 'Quantor — подсчёт строительных объёмов',
  description:
    'Портал работы с проектной документацией: проекты, распознанные пакеты и просмотр чертежей.',
  applicationName: 'Quantor',
  manifest: '/manifest.json',
  icons: {
    icon: [
      { url: '/quantor-favicon.svg', type: 'image/svg+xml' },
      { url: '/favicon-32.png', sizes: '32x32', type: 'image/png' },
    ],
    // iOS манифест не читает: размеры ярлыка задаются только этими тегами.
    apple: [
      { url: '/apple-touch-icon.png', sizes: '180x180' },
      { url: '/apple-touch-icon-167.png', sizes: '167x167' },
      { url: '/apple-touch-icon-152.png', sizes: '152x152' },
      { url: '/apple-touch-icon-120.png', sizes: '120x120' },
    ],
  },
  appleWebApp: {
    capable: true,
    title: 'Quantor',
    // Прозрачная строка состояния: под ней рисуется фон портала, и шапка
    // установленного приложения не выглядит чужой полосой.
    statusBarStyle: 'black-translucent',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  // Значение перезаписывается предзагрузочным скриптом под активную тему.
  themeColor: '#f1f4f7',
};

const RootLayout = ({ children }: { children: ReactNode }) => (
  <html lang="ru" suppressHydrationWarning>
    <body className="antialiased">
      <ThemeScript />
      <Providers>{children}</Providers>
      <ServiceWorkerBridge />
    </body>
  </html>
);

export default RootLayout;
