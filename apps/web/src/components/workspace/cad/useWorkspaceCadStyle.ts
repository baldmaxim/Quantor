'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { cadCodeText, cadErrorText } from '@/lib/cad/errors';
import {
  addStyleSample,
  removeStyleSample,
  type StyleClass,
  type StyleSample,
} from '@/lib/cad/style-profile';
import {
  useAcceptStylePreview,
  useCreateStylePreview,
  useStylePreviewJob,
  useStyleProfile,
} from '@/lib/cad/style-profile-queries';
import { isActiveStatus } from '@/lib/cad/queries';
import type { Camera } from '@/lib/viewer/camera';

import type { IWorkspaceCadStyle, IWorkspaceCadStylePreview } from './types';

interface IInput {
  projectId: string;
  /** Документ (том) открытой ревизии; `null` - ещё не известен. */
  documentId: string | null;
  revisionId: string | null;
  /** Индекс страницы открытого листа. */
  pageIndex: number | null;
  /** Размер страницы у отрисовщика; `null` - ещё не известен. */
  pageSize: { width: number; height: number } | null;
  camera: Camera;
  /** Флаг `cad.export` включён и вкладка CAD открывалась хотя бы раз. */
  load: boolean;
  /** Вкладка CAD открыта: слой образцов работает только на ней. */
  active: boolean;
  /** Холст занят другим режимом (замечание, зона). */
  blocked: boolean;
}

/** Данные слоя образцов для `<CadStyleCapture>`; `null` - режим выключен. */
export interface IStyleCaptureData {
  readonly camera: Camera;
  readonly page: { readonly width: number; readonly height: number };
  readonly samples: readonly StyleSample[];
  readonly onSample: (point: { x: number; y: number }) => void;
  readonly onExit: () => void;
}

export interface IWorkspaceCadStyleState {
  readonly side: IWorkspaceCadStyle | null;
  readonly capture: IStyleCaptureData | null;
}

/**
 * Профиль оформления тома в рабочей области: чтение профиля, образцы-щелчки открытого листа,
 * предпросмотр заданием и принятие. Образцы принадлежат листу: смена листа или ревизии их
 * сбрасывает, любое изменение образцов отзывает предпросмотр (принять можно только то, что видели).
 */
export const useWorkspaceCadStyle = ({
  projectId,
  documentId,
  revisionId,
  pageIndex,
  pageSize,
  camera,
  load,
  active,
  blocked,
}: IInput): IWorkspaceCadStyleState => {
  const profile = useStyleProfile(projectId, documentId, load);
  const createPreview = useCreateStylePreview(projectId, documentId);
  const accept = useAcceptStylePreview(projectId, documentId);

  const [sampling, setSampling] = useState(false);
  const [samples, setSamples] = useState<readonly StyleSample[]>([]);
  const [activeClass, setActiveClass] = useState<StyleClass>('monolith');
  const [negative, setNegative] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  const job = useStylePreviewJob(projectId, documentId, jobId);
  // Номер запроса предпросмотра: поздний ответ отозванного запроса `jobId` не ставит.
  const requestRef = useRef(0);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    // Смена листа или ревизии отзывает запрос, поставленный до неё.
    requestRef.current += 1;
  }, [epoch]);

  // Образцы принадлежат листу: другой лист или ревизия - чистое состояние.
  const scope = `${revisionId ?? ''}:${pageIndex ?? ''}`;
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setSampling(false);
    setSamples([]);
    setJobId(null);
    setEpoch((value) => value + 1);
    createPreview.reset();
    accept.reset();
  }

  const revokePreview = () => {
    requestRef.current += 1;
    setJobId(null);
    createPreview.reset();
    accept.reset();
  };

  // Полный сброс: после принятия.
  const stop = () => {
    setSampling(false);
    setSamples([]);
    revokePreview();
  };

  // Выход из режима (Esc, кнопка): образцы и предпросмотр остаются до повторного входа.
  const exit = () => setSampling(false);

  const onSample = (point: { x: number; y: number }) => {
    // Идёт принятие: образцы не меняются, иначе сброс потерял бы его результат.
    if (accept.isPending) return;
    setSamples((current) =>
      addStyleSample(current, { class: activeClass, x: point.x, y: point.y, negative }),
    );
    revokePreview();
  };

  const jobData = jobId !== null ? (job.data ?? null) : null;
  const preview = useMemo<IWorkspaceCadStylePreview | null>(() => {
    if (createPreview.isError) {
      return { running: false, result: null, error: cadErrorText(createPreview.error) };
    }
    if (createPreview.isPending) return { running: true, result: null, error: null };
    if (jobId === null) return null;
    if (job.isError) return { running: false, result: null, error: cadErrorText(job.error) };
    if (jobData === null || isActiveStatus(jobData.status)) {
      return { running: true, result: null, error: null };
    }
    if (jobData.status === 'succeeded' && jobData.result !== null) {
      return { running: false, result: jobData.result, error: null };
    }
    const code = jobData.error_code !== null ? cadCodeText(jobData.error_code) : null;
    const text = [code, jobData.error_message].filter((item) => item !== null && item !== '');
    return {
      running: false,
      result: null,
      error: text.length > 0 ? text.join(' ') : 'Предпросмотр не получен.',
    };
  }, [createPreview.isError, createPreview.isPending, createPreview.error, jobId, job.isError, job.error, jobData]);

  if (revisionId === null || documentId === null) return { side: null, capture: null };

  const current = profile.data?.current ?? null;
  const startDisabledReason = blocked
    ? 'Холст занят другим режимом: завершите разметку или отметку.'
    : pageSize === null || pageIndex === null
      ? 'Лист ещё не отрисован.'
      : null;

  const side: IWorkspaceCadStyle = {
    status:
      profile.data !== undefined ? 'ready' : profile.isError ? 'error' : 'loading',
    current,
    loadError: profile.isError ? cadErrorText(profile.error) : null,
    refreshError: profile.isError && profile.data !== undefined ? cadErrorText(profile.error) : null,
    onReload: () => void profile.refetch(),
    sampling,
    startDisabledReason,
    onStartSampling: () => {
      setSavedVersion(null);
      setSampling(true);
    },
    onStopSampling: exit,
    activeClass,
    onClassChange: setActiveClass,
    negative,
    onNegativeChange: setNegative,
    samples,
    onRemoveSample: (index) => {
      if (accept.isPending) return;
      setSamples((list) => removeStyleSample(list, index));
      revokePreview();
    },
    onClearSamples: () => {
      if (accept.isPending) return;
      setSamples([]);
      revokePreview();
    },
    preview,
    onPreview: () => {
      if (pageIndex === null || samples.length === 0) return;
      accept.reset();
      setJobId(null);
      const request = requestRef.current + 1;
      requestRef.current = request;
      createPreview.mutate(
        { revisionId, pageIndex, samples },
        {
          onSuccess: (id) => {
            if (requestRef.current === request) setJobId(id);
          },
        },
      );
    },
    accepting: accept.isPending,
    onAccept: (title) => {
      if (jobId === null || preview?.result == null) return;
      accept.mutate(
        {
          jobId,
          title,
          // Версия, на которой строился предпросмотр: её же видел человек.
          expectedCurrentVersion: preview.result.base_version,
        },
        {
          onSuccess: (version) => {
            setSavedVersion(version.version);
            stop();
          },
        },
      );
    },
    acceptError: accept.isError ? cadErrorText(accept.error) : null,
    savedVersion,
  };

  const capture: IStyleCaptureData | null =
    sampling && active && !blocked && pageSize !== null
      ? { camera, page: pageSize, samples, onSample, onExit: exit }
      : null;

  return { side, capture };
};
