'use client';

import { useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import { useAssignCadFinishTemplate, useCadFinishTemplates } from '@/lib/cad/finishes-queries';

import type { IWorkspaceCadZoneFinish } from './types';

/**
 * Назначение шаблона отделки выбранным зонам листа (ADR-0042): список шаблонов проекта и запись.
 * После назначения перечитываются зоны и ведомость; сервер пропускает двери и машино-места.
 */
export const useWorkspaceCadZoneFinish = (
  projectId: string,
  load: boolean,
): IWorkspaceCadZoneFinish => {
  const templates = useCadFinishTemplates(projectId, load);
  const assign = useAssignCadFinishTemplate(projectId);
  const [error, setError] = useState<string | null>(null);

  return {
    templates: templates.data ?? [],
    assigning: assign.isPending,
    error,
    onAssign: async (zoneIds, templateId) => {
      setError(null);
      try {
        const result = await assign.mutateAsync({ zoneIds, templateId });
        return { assigned: result.assigned, skipped: result.skipped_count };
      } catch (failure) {
        setError(cadErrorText(failure));
        return null;
      }
    },
  };
};
