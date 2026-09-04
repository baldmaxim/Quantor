import type { ReactNode } from 'react';

import { SideNav } from '@/components/shell/SideNav';

/**
 * Оболочка портала: рейка слева, содержимое справа.
 *
 * Общая для всех маршрутов, включая рабочую область: рейка нужна и там, иначе из
 * чертежа некуда вернуться. Высота фиксирована по окну — рабочая область должна
 * занимать её целиком, а не растягивать страницу.
 */
const PortalLayout = ({ children }: { children: ReactNode }) => (
  <div className="flex h-dvh">
    <SideNav />
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto">{children}</div>
  </div>
);

export default PortalLayout;
