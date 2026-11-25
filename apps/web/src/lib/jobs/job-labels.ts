import type { JobStatus, JobType } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/** Подписи заданий и состояний для эксплуатационных экранов: очередь по всем проектам. */

export const JOB_TYPE_LABELS: Readonly<Record<JobType, string>> = {
  legacy_import: 'Импорт пакета',
  pdf_geometry_extract: 'Геометрия PDF',
  cad_pdf_convert: 'CAD: конвертация',
  cad_mep_route: 'CAD: трассы',
  cad_walls: 'CAD: конструкции',
  cad_outline_review: 'CAD: проверка обводки',
  cad_ai_review: 'CAD: ИИ-проверка вида',
  cad_ai_vor_map: 'ВОР: сопоставление Claude',
  cad_floor3d_dxf: 'CAD: 3D DXF',
  cad_zones: 'CAD: зоны',
  cad_sections: 'CAD: разрезы',
  cad_facades: 'CAD: фасады',
  cad_eom_route: 'CAD: ЭОМ и СС',
  cad_style_preview: 'CAD: профиль оформления',
  model_ifc_import: 'Модель из IFC',
  sheet_passport_extract: 'Разбор паспортов листов',
  doc_questions_search: 'Вопросы к документации',
  sheet_register_extract: 'Ведомости листов',
  plan_align: 'Совмещение планов',
};

export const jobTypeLabel = (jobType: JobType): string => JOB_TYPE_LABELS[jobType] ?? jobType;

export interface IJobStatusView {
  readonly label: string;
  readonly tone: BadgeTone;
}

const JOB_STATUS_VIEWS: Readonly<Record<JobStatus, IJobStatusView>> = {
  queued: { label: 'В очереди', tone: 'neutral' },
  running: { label: 'Выполняется', tone: 'accent' },
  succeeded: { label: 'Готово', tone: 'success' },
  failed: { label: 'Ошибка', tone: 'danger' },
  cancelled: { label: 'Отменено', tone: 'neutral' },
};

export const jobStatusView = (status: JobStatus): IJobStatusView => JOB_STATUS_VIEWS[status];

/** Доля 0..1 в целые проценты; доли нет — `null` (выдуманных процентов не показываем). */
export const progressPercent = (progress: number | null): number | null =>
  progress === null ? null : Math.round(Math.min(Math.max(progress, 0), 1) * 100);
