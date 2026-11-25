import { CAD_FEATURE } from '@/lib/cad/access';
import { CONSISTENCY_FEATURE } from '@/lib/consistency/access';
import { MODEL_FEATURE } from '@/lib/model/model-access';
import { TENDER_EXCHANGE_FEATURE } from '@/lib/tender/access';
import { TENDER_VERSIONS_FEATURE } from '@/lib/tender-versions';

/**
 * Путь инженера по проекту: шаги по порядку, куда идти и одна строка «что сделать».
 *
 * Раньше разделы проекта стояли рядом кнопками без порядка (восемь в ряд, на 1280 px не
 * влезали), а «3D-модель объекта» и «Модель здания» не различались. Здесь и только здесь
 * решается, какие шаги есть, как они называются и что из чего следует. Шаг закрытого флагом
 * раздела не показывается; номера считаются по видимым шагам.
 */

export type ProjectStepKey =
  'documents' | 'sheets' | 'cad' | 'building' | 'model' | 'base' | 'access';

export interface IProjectStep {
  readonly key: ProjectStepKey;
  readonly title: string;
  /** Что сделать на шаге: коротко, без точки. */
  readonly hint: string;
  readonly href: string;
}

export interface IProjectLink {
  readonly label: string;
  readonly href: string;
}

type Features = Readonly<Record<string, boolean | undefined>>;

const on = (features: Features, flag: string): boolean => features[flag] === true;

export const projectSteps = (projectId: string, features: Features): IProjectStep[] => {
  const base = `/projects/${projectId}`;
  const steps: (IProjectStep | null)[] = [
    {
      key: 'documents',
      title: 'Документы',
      hint: 'загрузите PDF и IFC',
      href: base,
    },
    on(features, CONSISTENCY_FEATURE)
      ? {
          key: 'sheets',
          title: 'Листы комплекта',
          hint: 'разберите и подтвердите паспорта',
          href: `${base}/sheets`,
        }
      : null,
    on(features, CAD_FEATURE)
      ? {
          key: 'cad',
          title: 'CAD по листам',
          hint: 'документ → «Запустить конвейер»',
          href: base,
        }
      : null,
    on(features, CAD_FEATURE)
      ? {
          key: 'building',
          title: 'Здание',
          hint: 'этажи из листов в 3D',
          href: `${base}/building3d`,
        }
      : null,
    on(features, MODEL_FEATURE)
      ? {
          key: 'model',
          title: 'Модель здания',
          hint: 'из IFC; утвердите версию',
          href: `${base}/model`,
        }
      : null,
    on(features, TENDER_EXCHANGE_FEATURE)
      ? {
          key: 'base',
          title: 'База объекта',
          hint: 'выпуск для TENDER',
          href: `${base}/calcs?tab=base`,
        }
      : null,
    on(features, TENDER_EXCHANGE_FEATURE)
      ? {
          key: 'access',
          title: 'Доступ',
          hint: 'токены для TENDER и агентов',
          href: `${base}/calcs?tab=tokens`,
        }
      : null,
  ];
  return steps.filter((step): step is IProjectStep => step !== null);
};

/**
 * Следующий шаг после `current` с другим адресом: «CAD по листам» живёт на той же странице, что
 * «Документы», и следующим для документов не считается. Шага нет или он последний - `null`.
 */
export const nextProjectStep = (
  steps: readonly IProjectStep[],
  current: ProjectStepKey,
): IProjectStep | null => {
  const at = steps.findIndex((step) => step.key === current);
  if (at < 0) return null;
  const here = steps[at]?.href;
  return steps.slice(at + 1).find((step) => step.href !== here) ?? null;
};

/** Разделы проекта вне основного пути: открываются по надобности. */
export const projectExtraLinks = (projectId: string, features: Features): IProjectLink[] => {
  const base = `/projects/${projectId}`;
  return [
    on(features, CONSISTENCY_FEATURE)
      ? { label: 'Вопросы к документации', href: `${base}/doc-questions` }
      : null,
    on(features, CONSISTENCY_FEATURE) ? { label: 'Каркас здания', href: `${base}/frame` } : null,
    on(features, TENDER_VERSIONS_FEATURE)
      ? { label: 'Версии тендера', href: `${base}/versions` }
      : null,
    on(features, TENDER_EXCHANGE_FEATURE) ? { label: 'Расчёты', href: `${base}/calcs` } : null,
    on(features, CAD_FEATURE) ? { label: 'ВОР', href: `${base}/vor` } : null,
  ].filter((link): link is IProjectLink => link !== null);
};
