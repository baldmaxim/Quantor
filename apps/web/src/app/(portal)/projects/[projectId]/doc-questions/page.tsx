'use client';

import { use } from 'react';

import { DocQuestionsScreen } from '@/components/consistency/DocQuestionsScreen';

/** Вопросы к документации (ADR-0043, шаг 2). Закрыто флагом `project.consistency`. */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const DocQuestionsPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  return <DocQuestionsScreen projectId={projectId} />;
};

export default DocQuestionsPage;
