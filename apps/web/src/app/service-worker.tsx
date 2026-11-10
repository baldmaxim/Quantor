'use client';

import { Button } from '@/components/ui';
import { useAppUpdate } from '@/lib/useAppUpdate';

/**
 * Тост «Доступна новая версия портала». Логика — в useAppUpdate.
 *
 * Обновление не применяется молча: пользователь может в этот момент грузить
 * пятидесятимегабайтный пакет, и подмена кода под работающей вкладкой оборвала бы
 * загрузку. Поэтому новый worker ждёт, а на экране появляется предложение.
 *
 * В разработке не регистрируется: кэш перекрывал бы горячую перезагрузку.
 */

export const ServiceWorkerBridge = () => {
  const { visible, dismiss, apply } = useAppUpdate();

  if (!visible) return null;

  return (
    <div
      role="status"
      // Над нижней навигацией, а не поверх неё: на телефоне разделы прибиты к низу
      // экрана, и тост, лежащий на них, забирает себе нажатия по «Проектам».
      className="animate-rise fixed inset-x-[var(--s-5)] bottom-[calc(var(--h-bottom-nav)+var(--s-5)+var(--safe-b))] z-40 mx-auto flex max-w-[420px] flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface-raised px-[var(--s-5)] py-[var(--s-4)] shadow-[var(--shadow-2)] md:bottom-[calc(var(--s-6)+var(--safe-b))]"
    >
      <p className="min-w-0 flex-1 text-sm">Доступна новая версия портала</p>
      {/* Отложить можно: обновление перезагружает страницу, а пользователь мог
          в этот момент заполнять форму. */}
      <Button onClick={dismiss}>Позже</Button>
      <Button variant="primary" onClick={apply}>
        Обновить
      </Button>
    </div>
  );
};
