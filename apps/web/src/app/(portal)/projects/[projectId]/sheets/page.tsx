'use client';

import { use } from 'react';

import { SheetPassportsScreen } from '@/components/consistency/SheetPassportsScreen';

/** Листы комплекта (ADR-0043, С1). Закрыто флагом `project.consistency`. */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const SheetsPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  return <SheetPassportsScreen projectId={projectId} />;
};

export default SheetsPage;
