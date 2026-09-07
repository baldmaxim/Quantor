import { ThemeScript } from '@quantor/ui';
import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import { Providers } from '@/app/providers';

import './globals.css';

/**
 * Корневая разметка контура управления.
 *
 * Без service worker и без манифеста, в отличие от портала: контур управления без сети
 * бесполезен, а закэшированное состояние системы вводит в заблуждение — администратор
 * приходит сюда как раз тогда, когда что-то сломалось (ADR-0013).
 */

export const metadata: Metadata = {
  title: 'Управление платформой — Quantor',
  description: 'Контур управления Quantor: доступы, настройки, флаги, интеграции, журнал.',
  robots: { index: false, follow: false },
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
    <body>
      <Providers>{children}</Providers>
    </body>
  </html>
);

export default RootLayout;
