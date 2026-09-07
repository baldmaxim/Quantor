import type { ReactNode } from 'react';

import { BottomNav } from '@/components/shell/BottomNav';
import { SideNav } from '@/components/shell/SideNav';

/**
 * Оболочка портала.
 *
 * На десктопе разделы слева рейкой, на телефоне — внизу: вертикальная рейка на узком
 * экране съедала бы шестую часть ширины, а до её верха не дотянуться большим пальцем.
 *
 * Высота фиксирована по окну — рабочая область должна занимать её целиком, а не
 * растягивать страницу.
 */
const PortalLayout = ({ children }: { children: ReactNode }) => (
  <div className="flex h-dvh flex-col md:flex-row">
    <SideNav />
    <div className="scroll-area flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
    <BottomNav />
  </div>
);

export default PortalLayout;
