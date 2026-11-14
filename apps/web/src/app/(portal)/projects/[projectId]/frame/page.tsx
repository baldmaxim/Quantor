'use client';

import { use } from 'react';

import { FrameScreen } from '@/components/consistency/FrameScreen';

/** Каркас здания (ADR-0043, С2). Закрыто флагом `project.consistency`. */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const FramePage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  return <FrameScreen projectId={projectId} />;
};

export default FramePage;
