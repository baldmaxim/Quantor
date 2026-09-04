import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';
import { Providers } from './providers';
import { ThemeScript } from './theme-script';

export const metadata: Metadata = {
  title: 'Quantor — подсчёт строительных объёмов',
  description:
    'Портал работы с проектной документацией: проекты, распознанные пакеты и просмотр чертежей.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

const RootLayout = ({ children }: { children: ReactNode }) => (
  <html lang="ru" suppressHydrationWarning>
    <head>
      <ThemeScript />
    </head>
    <body className="antialiased">
      <Providers>{children}</Providers>
    </body>
  </html>
);

export default RootLayout;
