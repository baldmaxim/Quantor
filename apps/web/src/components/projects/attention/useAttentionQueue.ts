'use client';

import { readCadPipeline, type CadPipelineRead } from '@quantor/api-client';
import { useQueries } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { CAD_FEATURE } from '@/lib/cad/access';
import { CONSISTENCY_FEATURE } from '@/lib/consistency/access';
import { useDocQuestions } from '@/lib/consistency/doc-question-queries';
import { latestOpenableRevision } from '@/lib/openability';
import { useProjectPipelineAuto } from '@/lib/pipeline-auto-queries';
import { unwrap, useFeatures, useProjectDocuments, useProjectRevisions } from '@/lib/queries';

import {
  AUTO_OPEN_GAP_MS,
  SNOOZE_MS,
  buildAttentionQueue,
  docItems,
  readLastAutoOpen,
  readSnoozed,
  scaleItem,
  writeLastAutoOpen,
  writeSnoozed,
  type AttentionItem,
  type IScaleItem,
  type Snoozed,
} from './attentionQueue';

/**
 * Очередь прямых вопросов человеку по проекту (автопайплайн, S0-B).
 *
 * Собирается из существующих запросов: вопросы к документации (флаг `project.consistency`) и
 * конвейер CAD последних PDF-ревизий (флаг CAD). Пока `pipeline-auto` не включён для проекта,
 * ничего не запрашивается и ничего не показывается. Окно само открывается не чаще раза в 2
 * минуты; «Позже» откладывает вопрос на сутки (localStorage).
 */

/** Сколько последних PDF-ревизий проверяется на масштаб CAD: запросов не должно быть много. */
const MAX_REVISIONS = 8;
const CAD_POLL_MS = 30_000;
const CAD_STALE_MS = 15_000;
const AUTO_OPEN_CHECK_MS = 30_000;
const NO_SNOOZED: Snoozed = {};

interface ITarget {
  readonly revisionId: string;
  readonly documentName: string;
}

const dataOnly = (results: readonly { data: CadPipelineRead | undefined }[]) =>
  results.map((result) => result.data);

export interface IAttentionQueue {
  readonly enabled: boolean;
  readonly items: readonly AttentionItem[];
  readonly open: boolean;
  readonly setOpen: (value: boolean) => void;
  /** Отложить вопрос на 24 часа. */
  readonly snooze: (id: string) => void;
}

export const useAttentionQueue = (projectId: string): IAttentionQueue => {
  const auto = useProjectPipelineAuto(projectId);
  const enabled = auto.data?.enabled === true;
  const features = useFeatures();
  const consistency = enabled && features[CONSISTENCY_FEATURE] === true;
  const cad = enabled && features[CAD_FEATURE] === true;

  const questions = useDocQuestions(projectId, consistency);
  const documents = useProjectDocuments(projectId, cad);
  const documentList = useMemo(() => documents.data?.items ?? [], [documents.data]);
  const revisions = useProjectRevisions(
    projectId,
    documentList.map((document) => document.id),
    cad,
  );

  const targets = useMemo<ITarget[]>(() => {
    const found: ITarget[] = [];
    for (const document of documentList) {
      const revision = latestOpenableRevision(
        document,
        revisions.byDocument.get(document.id)?.items ?? [],
      );
      if (revision) found.push({ revisionId: revision.id, documentName: document.display_name });
    }
    return found.slice(0, MAX_REVISIONS);
  }, [documentList, revisions.byDocument]);

  const pipelines = useQueries({
    queries: targets.map((target) => ({
      queryKey: cadPipelineKey(projectId, target.revisionId),
      enabled: cad,
      queryFn: async () =>
        unwrap(
          await readCadPipeline({
            throwOnError: true,
            path: { project_id: projectId, revision_id: target.revisionId },
          }),
        ),
      staleTime: CAD_STALE_MS,
      refetchInterval: CAD_POLL_MS,
    })),
    combine: dataOnly,
  });

  const scale = useMemo<IScaleItem[]>(
    () =>
      targets.flatMap((target, index) =>
        (pipelines[index]?.sheets ?? []).flatMap((sheet) => {
          const item = scaleItem(projectId, target.revisionId, target.documentName, sheet);
          return item ? [item] : [];
        }),
      ),
    [targets, pipelines, projectId],
  );
  const docs = useMemo(() => docItems(questions.data), [questions.data]);

  // Время загрузки страницы: истёкшие отсрочки отбрасываются при чтении, новые заведомо позже.
  const [loadedAt] = useState(() => Date.now());
  const [stored, setStored] = useState(() => ({
    projectId,
    map: readSnoozed(projectId, loadedAt),
  }));
  if (stored.projectId !== projectId) {
    setStored({ projectId, map: readSnoozed(projectId, loadedAt) });
  }
  const snoozed: Snoozed = stored.projectId === projectId ? stored.map : NO_SNOOZED;

  const items = useMemo(
    () => (enabled ? buildAttentionQueue(scale, docs, snoozed, loadedAt) : []),
    [enabled, scale, docs, snoozed, loadedAt],
  );

  const snooze = useCallback(
    (id: string) =>
      setStored((current) => {
        const map = {
          ...(current.projectId === projectId ? current.map : {}),
          [id]: Date.now() + SNOOZE_MS,
        };
        writeSnoozed(projectId, map);
        return { projectId, map };
      }),
    [projectId],
  );

  const [open, setOpen] = useState(false);
  const lastAuto = useRef(0);
  const count = items.length;

  useEffect(() => {
    if (!enabled || open || count === 0) return;
    const tryOpen = () => {
      const now = Date.now();
      const last = Math.max(lastAuto.current, readLastAutoOpen(projectId));
      if (now - last < AUTO_OPEN_GAP_MS) return;
      lastAuto.current = now;
      writeLastAutoOpen(projectId, now);
      setOpen(true);
    };
    tryOpen();
    const timer = window.setInterval(tryOpen, AUTO_OPEN_CHECK_MS);
    return () => window.clearInterval(timer);
  }, [enabled, open, count, projectId]);

  return { enabled, items, open, setOpen, snooze };
};
