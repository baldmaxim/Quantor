import type { ReactNode } from 'react';
import { redirect } from 'next/navigation';

import { BottomNav } from '@/components/shell/BottomNav';
import { SideNav } from '@/components/shell/SideNav';
import { fetchServerSession } from '@/lib/server-session';

/**
 * Оболочка портала.
 *
 * На десктопе разделы слева рейкой, на телефоне — внизу: вертикальная рейка на узком
 * экране съедала бы шестую часть ширины, а до её верха не дотянуться большим пальцем.
 *
 * Высота фиксирована по окну — рабочая область должна занимать её целиком, а не
 * растягивать страницу.
 *
 * Сеанс проверяется здесь, на сервере, до отрисовки. Клиентская проверка опоздала бы:
 * разметка уже ушла бы в браузер, а запросы за проектами — на сервер.
 */
const PortalLayout = async ({ children }: { children: ReactNode }) => {
  const session = await fetchServerSession();

  // Отказ и недоступность API — разные вещи. Первое ведёт на страницу входа; второе
  // оставляет оболочку, и запросы внутри честно покажут, что сервер не отвечает.
  if (session !== null && !session.authenticated) {
    redirect('/signed-out');
  }

  return (
    <div className="flex h-dvh flex-col md:flex-row">
      <SideNav />
      <div className="scroll-area flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
      <BottomNav />
    </div>
  );
};

export default PortalLayout;
