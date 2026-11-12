import type { BadgeTone } from '@/components/ui';

import type { PipelineStepState } from './pipeline';

/** Общие подписи состояний шага конвейера: тон бейджа, значок и слово для чтения с экрана. */

export const PIPELINE_STATE_TONES: Readonly<Record<PipelineStepState, BadgeTone>> = {
  todo: 'neutral',
  queued: 'accent',
  running: 'accent',
  done: 'success',
  review: 'warning',
  failed: 'danger',
  skipped: 'neutral',
  blocked: 'neutral',
};

export const PIPELINE_STATE_GLYPHS: Readonly<Record<PipelineStepState, string>> = {
  todo: '○',
  queued: '◷',
  running: '…',
  done: '✓',
  review: '!',
  failed: '×',
  skipped: '–',
  blocked: '·',
};

export const PIPELINE_STATE_WORDS: Readonly<Record<PipelineStepState, string>> = {
  todo: 'не начато',
  queued: 'в очереди',
  running: 'идёт',
  done: 'готово',
  review: 'нужно решение',
  failed: 'ошибка',
  skipped: 'не требуется',
  blocked: 'ждёт предыдущего шага',
};
