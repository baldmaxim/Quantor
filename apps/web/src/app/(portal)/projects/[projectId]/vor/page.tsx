'use client';

import { use } from 'react';

import { VorFillScreen } from '@/components/vor-fill/VorFillScreen';

/** Заполнение ВОР Заказчика (ADR-0055, п. 7). Закрыто флагом `cad.export`. */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const VorFillPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  return <VorFillScreen projectId={projectId} />;
};

export default VorFillPage;
