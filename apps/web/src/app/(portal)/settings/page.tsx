'use client';

import { ViewTransition } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { Button, Field, StatusBadge } from '@/components/ui';
import { useMeta } from '@/lib/queries';
import { toggleTheme, useTheme } from '@/lib/theme';

/**
 * Настройки.
 *
 * На этом этапе здесь только то, что действительно работает: тема и сведения о том,
 * с каким API общается интерфейс. Выдуманных разделов не добавляем.
 */
const SettingsPage = () => {
  const meta = useMeta();
  const theme = useTheme();

  return (
    <>
      <TopBar crumbs={[{ label: 'Настройки' }]} />

      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[720px] flex-col gap-[var(--s-6)]">
          <section className="rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)] md:p-[var(--s-6)]">
            <h2 className="mb-[var(--s-4)] text-sm font-medium">Оформление</h2>
            <div className="flex flex-col items-start gap-[var(--s-5)] sm:flex-row sm:items-center sm:gap-[var(--s-6)]">
              <p className="text-sm text-muted">
                Сейчас: {theme === 'dark' ? 'тёмная' : 'светлая'} тема. По умолчанию портал следует
                системной настройке.
              </p>
              <Button className="flex-none sm:ml-auto" onClick={() => toggleTheme()}>
                Переключить
              </Button>
            </div>
          </section>

          <section className="rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)] md:p-[var(--s-6)]">
            <h2 className="mb-[var(--s-4)] text-sm font-medium">Подключение</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-6)] gap-y-[var(--s-2)]">
              <Field label="Контракт API">{meta.data?.api_version ?? '…'}</Field>
              <Field label="Схема данных">{meta.data?.schema_version ?? '…'}</Field>
              <Field label="Окружение">{meta.data?.environment ?? '…'}</Field>
              <Field label="Этап">{meta.data?.stage ?? '…'}</Field>
            </dl>
          </section>

          <section className="rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)] md:p-[var(--s-6)]">
            <h2 className="mb-[var(--s-4)] text-sm font-medium">Возможности</h2>
            <p className="mb-[var(--s-5)] text-sm text-muted">
              Список приходит от сервера. Выключенное здесь выключено и в интерфейсе.
            </p>
            <ul className="flex flex-wrap gap-[var(--s-4)]">
              {Object.entries(meta.data?.features ?? {}).map(([name, enabled]) => (
                <li key={name}>
                  <StatusBadge tone={enabled ? 'success' : 'neutral'}>
                    <span className="mono">{name}</span>
                  </StatusBadge>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </main>
    </>
  );
};

const SettingsRoute = () => (
  <ViewTransition
    enter={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
    exit={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
    default="none"
  >
    <SettingsPage />
  </ViewTransition>
);

export default SettingsRoute;
