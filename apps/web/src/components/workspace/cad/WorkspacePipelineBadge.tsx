'use client';

import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { useWorkspaceStore } from '@/store/workspace';

import type { IWorkspaceCadPipeline } from './useWorkspaceCadPipeline';

export interface IWorkspacePipelineBadgeProps {
  readonly pipeline: IWorkspaceCadPipeline;
  /** Флаг `cad.export`: без него бейдж не показывается вовсе. */
  readonly cadOn: boolean;
  /** Открывает раздел «Обработка» правой панели (режим CAD бейдж включает сам). */
  readonly onOpen: () => void;
}

export const NOT_PROCESSED_LABEL = 'Лист не обрабатывался';

/** Итог обработки листа в шапке рабочей области; нажатие включает режим CAD и открывает «Обработку». */
export const WorkspacePipelineBadge: FC<IWorkspacePipelineBadgeProps> = ({
  pipeline,
  cadOn,
  onOpen,
}) => {
  const setMode = useWorkspaceStore((state) => state.setMode);
  if (!cadOn || pipeline.isPending || pipeline.isError) return null;
  const tone = pipeline.summary?.tone ?? 'neutral';
  const label = pipeline.summary?.label ?? NOT_PROCESSED_LABEL;
  return (
    <button
      type="button"
      onClick={() => {
        setMode('cad');
        onOpen();
      }}
      aria-label={`Обработка листа: ${label}`}
      className="inline-flex min-h-[44px] touch-manipulation items-center md:min-h-8"
    >
      <StatusBadge tone={tone}>{label}</StatusBadge>
    </button>
  );
};
