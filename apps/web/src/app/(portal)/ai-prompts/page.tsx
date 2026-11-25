'use client';

import { AiPromptsBoard } from '@/components/ai-prompts/AiPromptsBoard';
import { TopBar } from '@/components/shell/TopBar';

/** Промты ИИ-проверки: версии, правка, активация и статистика (системный администратор). */
const AiPromptsPage = () => (
  <>
    <TopBar crumbs={[{ label: 'Настройки', href: '/settings' }, { label: 'Промты ИИ' }]} />
    <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
      <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-[var(--s-6)]">
        <h1 className="m-0 text-lg font-medium">Промты ИИ</h1>
        <AiPromptsBoard />
      </div>
    </main>
  </>
);

export default AiPromptsPage;
