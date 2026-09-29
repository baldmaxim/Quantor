import type { ReactNode } from 'react';

/**
 * Каркас экранов входа: одна карточка по центру, без оболочки портала.
 *
 * Тому, кто не вошёл, рейка разделов ничего не даёт, а её вид создавал бы впечатление,
 * что доступ уже есть. На телефоне карточка занимает ширину экрана с полями по краям.
 */

interface IAuthLayoutProps {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}

export const AuthLayout = ({ title, description, children }: IAuthLayoutProps) => (
  <main className="grid min-h-dvh place-items-center px-[var(--s-6)] py-[var(--s-8)] pt-[max(var(--s-8),env(safe-area-inset-top))] pb-[max(var(--s-8),env(safe-area-inset-bottom))]">
    <div className="flex w-full max-w-[400px] flex-col gap-[var(--s-6)]">
      <div className="flex flex-col gap-[var(--s-3)] text-center">
        <span className="text-micro font-semibold tracking-[0.12em] text-muted uppercase">
          Quantor
        </span>
        <h1 className="text-xl font-semibold tracking-[-0.02em]">{title}</h1>
        {description && <p className="text-sm text-muted">{description}</p>}
      </div>
      {children}
    </div>
  </main>
);
