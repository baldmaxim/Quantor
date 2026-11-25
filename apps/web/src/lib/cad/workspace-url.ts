import type { CadJobSummaryRead, SheetRead } from '@quantor/api-client';

import { asIndex, asUuid, type ICadSelection } from './selection';

/**
 * Адрес вкладки CAD в рабочей области: `?revision=&page=<позиция листа с 1>&tab=cad&job=&view=`.
 * `page` рабочей области - позиция листа в ревизии, а не индекс страницы PDF (`page_index`);
 * здесь живёт перевод одного в другое.
 */

/** Позиция листа в рабочей области (с 1) по индексу страницы PDF; `null` - листа нет. */
export const sheetPosition = (
  sheets: readonly Pick<SheetRead, 'page_index'>[],
  pageIndex: number,
): number | null => {
  const at = sheets.findIndex((sheet) => sheet.page_index === pageIndex);
  return at < 0 ? null : at + 1;
};

export interface IWorkspaceCadTarget {
  readonly revision: string | null;
  /** Позиция листа с 1; `null` - лист не указан. */
  readonly position: number | null;
  readonly job: string | null;
  readonly view: number | null;
  /**
   * Раздел правой панели CAD, который открыть сразу (`zones`, `mep`…): кнопка «Одобрить вид»
   * лежит в «Трассах», ручная разметка - в «Зонах». Нет - панель выберет сама.
   */
  readonly side?: string | null;
}

/** Ссылка в рабочую область на вкладку CAD. Без ревизии - только вкладка. */
export const workspaceCadHref = (projectId: string, target: IWorkspaceCadTarget): string => {
  const params = new URLSearchParams();
  if (target.revision) {
    params.set('revision', target.revision);
    if (target.position !== null) params.set('page', String(target.position));
  }
  params.set('tab', 'cad');
  if (target.revision && target.job) {
    params.set('job', target.job);
    if (target.view !== null) params.set('view', String(target.view));
  }
  if (target.side) params.set('side', target.side);
  return `/projects/${projectId}/workspace?${params.toString()}`;
};

/**
 * Старый адрес страницы CAD (`?revision&job&page=<индекс>&view`) -> адрес рабочей области.
 * Лист вне списка (список не получен) адресуется по индексу: позиция обычно ему равна.
 */
export const cadRedirectHref = (
  projectId: string,
  selection: ICadSelection,
  sheets: readonly Pick<SheetRead, 'page_index'>[] | null,
): string => {
  const position =
    selection.page === null
      ? null
      : ((sheets ? sheetPosition(sheets, selection.page) : null) ?? selection.page + 1);
  return workspaceCadHref(projectId, {
    revision: selection.revision,
    position,
    job: selection.job,
    view: selection.view,
  });
};

/**
 * Задание и вид из адреса рабочей области; невалидное отбрасывается. Вид читается и без задания
 * (ссылка со страницы «Расчёты»): тогда он выбирается у самого нового готового задания листа.
 */
export const parseWorkspaceJob = (params: {
  get: (name: string) => string | null;
}): { readonly job: string | null; readonly view: number | null } => ({
  job: asUuid(params.get('job')),
  view: asIndex(params.get('view')),
});

/** Задание закрывает лист: страницы не названы («все плановые») либо среди них есть этот лист. */
export const jobCoversPage = (
  job: Pick<CadJobSummaryRead, 'requested_pages'>,
  pageIndex: number,
): boolean => {
  const pages = job.requested_pages ?? [];
  return pages.length === 0 || pages.includes(pageIndex);
};

/**
 * Лист, на который перейти при выборе задания: текущий, если задание его покрывает, иначе первая
 * из заказанных страниц. Так выбор задания не оставляет рабочую область на постороннем листе.
 */
export const pageForJob = (
  job: Pick<CadJobSummaryRead, 'requested_pages'>,
  currentPage: number | null,
): number | null => {
  if (currentPage !== null && jobCoversPage(job, currentPage)) return currentPage;
  const pages = job.requested_pages ?? [];
  return pages.length > 0 ? Math.min(...pages) : currentPage;
};
