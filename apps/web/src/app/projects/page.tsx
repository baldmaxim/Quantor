import { ApiStatus } from '@/components/ApiStatus';

/**
 * Заглушка списка проектов. Реальный список, поиск и создание проекта появятся вместе
 * с оболочкой портала — сейчас страница подтверждает, что фронтенд и API связаны.
 */
const ProjectsPage = () => (
  <main className="mx-auto flex min-h-dvh w-full max-w-3xl flex-col gap-8 px-6 py-16">
    <header className="flex flex-col gap-2">
      <p className="font-mono text-xs tracking-widest text-muted uppercase">Quantor</p>
      <h1 className="text-2xl font-semibold">Проекты</h1>
      <p className="text-sm text-muted">Подсчёт строительных объёмов по проектной документации.</p>
    </header>

    <section className="rounded-lg border border-border bg-surface p-6">
      <h2 className="text-base font-medium">Проектов пока нет</h2>
      <p className="mt-2 text-sm text-muted">
        Создание проектов и загрузка распознанных пакетов появятся на следующем шаге разработки.
      </p>
    </section>

    <section className="rounded-lg border border-border bg-surface-muted p-6">
      <h2 className="mb-3 text-base font-medium">Состояние API</h2>
      <ApiStatus />
    </section>
  </main>
);

export default ProjectsPage;
