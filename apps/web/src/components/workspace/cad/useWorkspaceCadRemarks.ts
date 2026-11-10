'use client';

import { useEffect, useMemo, useState } from 'react';

import { useCadRemarks, type IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { BboxPt, IRemarkBinding } from '@/lib/cad/remarks';
import {
  IDLE_REMARK_BINDING,
  WORKSPACE_DRAFT_ID,
  workspaceMarks,
} from '@/lib/cad/workspace-cad';
import type { IRemarkMark } from '@/lib/cad/remarks-painter';
import type { Camera, Viewport } from '@/lib/viewer/camera';

import type { IWorkspaceCadRemarks } from './types';

interface IInput {
  binding: IRemarkBinding | null;
  /** Размер листа у отрисовщика (pt при масштабе 1); `null` - ещё не известен. */
  pageSize: { width: number; height: number } | null;
  camera: Camera;
  viewportSize: () => Viewport;
  /** Вкладка CAD открыта: рамки рисуются и отметка работает только на ней. */
  active: boolean;
}

export interface IWorkspaceCadRemarksState {
  readonly remarks: IWorkspaceCadRemarks | null;
  /** Рамки замечаний и черновика на листе. */
  readonly marks: readonly IRemarkMark[];
  readonly activeId: string | null;
  /** Режим отметки включён: поверх холста нужен слой захвата рамки. */
  readonly capturing: boolean;
  readonly onDrawn: (bbox: BboxPt) => void;
}

/** Замечания вида: отметка участка, черновик, выбранное замечание и рамки на листе. */
export const useWorkspaceCadRemarks = ({
  binding,
  pageSize,
  camera,
  viewportSize,
  active,
}: IInput): IWorkspaceCadRemarksState => {
  const store = useCadRemarks(binding ?? IDLE_REMARK_BINDING, binding !== null);

  const [marking, setMarking] = useState(false);
  const [draft, setDraft] = useState<BboxPt | null>(null);
  const [activeRemark, setActiveRemark] = useState<string | null>(null);

  // Участок и выбор принадлежат виду: на другом листе или виде они означали бы другое место.
  // Закрытая вкладка тоже гасит режим отметки, чтобы он не включился сам при возвращении.
  const scope = binding ? `${binding.jobId}:${binding.pageIndex}:${binding.view}` : null;
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setMarking(false);
    setDraft(null);
    setActiveRemark(null);
  }
  if (!active && marking) setMarking(false);

  const markDisabledReason =
    pageSize === null ? 'Отметка станет доступна, когда загрузится страница PDF.' : null;
  const markingOn = marking && active && markDisabledReason === null;

  // Esc отменяет режим отметки, пока он включён.
  useEffect(() => {
    if (!markingOn) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMarking(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [markingOn]);

  const marks = useMemo(
    () => (active ? workspaceMarks(store.remarks, draft, pageSize) : []),
    [active, store.remarks, draft, pageSize],
  );

  // Участок нарисован: режим отметки гаснет, чтобы лист снова можно было двигать.
  const onDrawn = (bbox: BboxPt) => {
    setDraft(bbox);
    setMarking(false);
  };
  // Черновик закрывается только после ответа сервера: при отказе участок и текст остаются.
  const saveDraft = async (value: IRemarkDraft) => {
    if (!draft) return;
    const created = await store.add(draft, value);
    if (!created) return;
    setActiveRemark(created.id);
    setDraft(null);
  };

  const remarks: IWorkspaceCadRemarks | null = binding
    ? {
        binding,
        store,
        page: pageSize,
        marking: markingOn,
        onMarkingChange: setMarking,
        markDisabledReason,
        draft,
        onDraftSave: (value) => void saveDraft(value),
        onDraftCancel: () => setDraft(null),
        activeId: activeRemark,
        onActivate: setActiveRemark,
        onFocusCamera: (state) => camera.set(state),
        viewport: viewportSize,
      }
    : null;

  return {
    remarks,
    marks,
    activeId: draft ? WORKSPACE_DRAFT_ID : activeRemark,
    capturing: markingOn && pageSize !== null,
    onDrawn,
  };
};
