'use client';

import { Suspense, use } from 'react';

import { TenderCalcsScreen } from '@/components/tender/TenderCalcsScreen';

/** Расчёты TENDER в проекте (ADR-0051): репозитории расчётов, база объекта, токены. Закрыто флагом `tender.exchange`. */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcsPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  return <TenderCalcsScreen projectId={projectId} />;
};

// `useSearchParams` требует границы Suspense: иначе страницу нельзя отдать статической оболочкой.
const CalcsRoute = ({ params }: IPageProps) => (
  <Suspense fallback={null}>
    <CalcsPage params={params} />
  </Suspense>
);

export default CalcsRoute;
