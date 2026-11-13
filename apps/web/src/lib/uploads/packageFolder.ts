import { extensionOf, isAccepted } from '@/lib/upload';

/**
 * Разбор папки, распакованной из ZIP распознанного пакета legacy-v1.
 *
 * Сервер принимает пакет только ZIP-файлом, поэтому папку приходится собирать обратно.
 * Эта функция только решает, что с чем сложить; сам архив собирает buildPackageZip.
 *
 * Комплект по stem: `<stem>.pdf`, `<stem>_results.md`, `<stem>_results.html`,
 * `<stem>_blocks.json`. Комплект без PDF, чей `<stem>.pdf` уже загружен в проект, идёт без PDF:
 * сервер прикрепит распознавание к этому PDF. Подпапки не важны (markdown/, attachments/, data/ и т.п.),
 * регистр расширений тоже.
 */

export interface IFolderEntry {
  readonly file: File;
  /** Путь внутри выбранной папки; для файла без папки — просто имя. */
  readonly path: string;
}

export interface IFolderPackage {
  readonly stem: string;
  /** null — комплект без PDF: распознавание прикрепится к PDF, уже лежащему в проекте. */
  readonly pdf: File | null;
  readonly resultsMd: File;
  readonly resultsHtml: File;
  readonly blocks: File;
}

export interface IFolderWarning {
  readonly stem: string;
  /** Имена файлов, которых не хватает до полного комплекта. */
  readonly missing: readonly string[];
}

export interface IFolderPlan {
  /** Полные комплекты: собираются в ZIP и идут как пакет. */
  readonly packages: readonly IFolderPackage[];
  /** PDF без распознавания и прочие поддерживаемые файлы: идут как обычные. */
  readonly plainFiles: readonly File[];
  /** Неполные комплекты и распознавание без PDF: не загружаются. */
  readonly warnings: readonly IFolderWarning[];
  /** Сколько файлов не относится ни к чему загружаемому. */
  readonly skipped: number;
}

type Role = 'pdf' | 'resultsMd' | 'resultsHtml' | 'blocks';

const SUFFIXES: readonly { readonly role: Exclude<Role, 'pdf'>; readonly suffix: string }[] = [
  { role: 'resultsMd', suffix: '_results.md' },
  { role: 'resultsHtml', suffix: '_results.html' },
  { role: 'blocks', suffix: '_blocks.json' },
];

const ROLE_ORDER: readonly Role[] = ['pdf', 'resultsMd', 'resultsHtml', 'blocks'];

const roleFileName = (stem: string, role: Role): string => {
  if (role === 'pdf') return `${stem}.pdf`;
  const found = SUFFIXES.find((item) => item.role === role);
  return `${stem}${found?.suffix ?? ''}`;
};

/**
 * Ключ сравнения имени комплекта с документом проекта: NFC, нижний регистр, пробелы и
 * подчёркивания — одно и то же (распознавалка заменяет пробелы имени PDF на `_`).
 */
export const stemKey = (stem: string): string =>
  stem.normalize('NFC').trim().toLowerCase().replace(/[\s_]+/g, '_');

export const baseName = (path: string): string => {
  const normalized = path.replace(/\\/g, '/');
  return normalized.slice(normalized.lastIndexOf('/') + 1);
};

/** Роль файла в комплекте и stem; null — файл к комплектам не относится. */
const classify = (name: string): { role: Role; stem: string } | null => {
  const lower = name.toLowerCase();

  for (const { role, suffix } of SUFFIXES) {
    if (lower.endsWith(suffix) && name.length > suffix.length) {
      return { role, stem: name.slice(0, name.length - suffix.length) };
    }
  }
  if (lower.endsWith('.pdf') && name.length > '.pdf'.length) {
    return { role: 'pdf', stem: name.slice(0, name.length - '.pdf'.length) };
  }
  return null;
};

interface IPlanned {
  readonly plan: IFolderPlan;
  /** Записи неполных комплектов по stem: их можно спланировать заново вместе с новыми файлами. */
  readonly incomplete: ReadonlyMap<string, readonly IFolderEntry[]>;
  /** Stem комплектов без PDF, идущих как пакет (PDF уже в проекте). */
  readonly attachToExisting: readonly string[];
}

const planEntries = (
  entries: readonly IFolderEntry[],
  attachableStems: ReadonlySet<string> = new Set(),
): IPlanned => {
  const groups = new Map<string, Partial<Record<Role, File>>>();
  const groupEntries = new Map<string, IFolderEntry[]>();
  const plainFiles: File[] = [];
  let skipped = 0;

  // Порядок по пути: результат не зависит от того, в каком порядке браузер отдал файлы.
  const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path, 'ru'));

  for (const entry of sorted) {
    const { file, path } = entry;
    const name = baseName(path);
    const part = classify(name);

    if (part) {
      const group = groups.get(part.stem) ?? {};
      if (group[part.role]) {
        // Второй файл с той же ролью в другой подпапке: какой из них нужный, неизвестно.
        skipped += 1;
      } else {
        group[part.role] = file;
        groups.set(part.stem, group);
        groupEntries.set(part.stem, [...(groupEntries.get(part.stem) ?? []), entry]);
      }
      continue;
    }

    // `_source.json`, `.DS_Store` и прочее — не наше; BIM и ZIP — как в обычном выборе.
    if (extensionOf(name) !== '' && isAccepted(name)) {
      plainFiles.push(file);
    } else {
      skipped += 1;
    }
  }

  const packages: IFolderPackage[] = [];
  const warnings: IFolderWarning[] = [];
  const incomplete = new Map<string, readonly IFolderEntry[]>();
  const attachToExisting: string[] = [];

  for (const [stem, group] of groups) {
    const { pdf, resultsMd, resultsHtml, blocks } = group;
    const hasRecognition = Boolean(resultsMd ?? resultsHtml ?? blocks);

    if (pdf && resultsMd && resultsHtml && blocks) {
      packages.push({ stem, pdf, resultsMd, resultsHtml, blocks });
    } else if (
      !pdf &&
      resultsMd &&
      resultsHtml &&
      blocks &&
      attachableStems.has(stemKey(stem))
    ) {
      packages.push({ stem, pdf: null, resultsMd, resultsHtml, blocks });
      attachToExisting.push(stem);
    } else if (pdf && !hasRecognition) {
      plainFiles.push(pdf);
    } else {
      warnings.push({
        stem,
        missing: ROLE_ORDER.filter((role) => !group[role]).map((role) => roleFileName(stem, role)),
      });
      incomplete.set(stem, groupEntries.get(stem) ?? []);
    }
  }

  return { plan: { packages, plainFiles, warnings, skipped }, incomplete, attachToExisting };
};

export const planFolderUpload = (entries: readonly IFolderEntry[]): IFolderPlan =>
  planEntries(entries).plan;

/** Не хватает только PDF: распознавание целиком есть, оригинал лежит в другой папке. */
export const isMissingOnlyPdf = ({ stem, missing }: IFolderWarning): boolean =>
  missing.length === 1 && missing[0] === roleFileName(stem, 'pdf');

export interface IMergeFolderInput {
  /** Записи неполных комплектов из прошлых добавлений. */
  readonly pending: readonly IFolderEntry[];
  /** Обычные PDF, уже выбранные и ещё не загруженные: могут достроить комплект. */
  readonly loosePdfs: readonly File[];
  /** Только что добавленное: папка или файлы. */
  readonly incoming: readonly IFolderEntry[];
  /** Базовые имена (нижний регистр) распознанных пакетов, уже лежащих в проекте. */
  readonly existingStems: ReadonlySet<string>;
  /** Базовые имена (нижний регистр, без `.pdf`) PDF-документов проекта. */
  readonly existingPdfStems: ReadonlySet<string>;
}

export interface IMergedPlan extends IFolderPlan {
  /** Что ждёт недостающих файлов; передаётся в следующий вызов. */
  readonly pending: readonly IFolderEntry[];
  /** Обычные PDF, ушедшие в комплекты или в ожидание: из списка файлов их надо убрать. */
  readonly consumed: readonly File[];
  /** Stem неполных комплектов, пакет которых уже есть в проекте. */
  readonly alreadyInProject: readonly string[];
  /** Stem комплектов без PDF: распознавание прикрепится к уже загруженному PDF. */
  readonly attachToExisting: readonly string[];
}

/**
 * План по новым записям вместе с ожидающими и уже выбранными PDF.
 *
 * Комплект собирается из нескольких выборов в любом порядке: распознавание из одной папки,
 * PDF из другой или из файлов. Обычный PDF без распознавания рядом не трогается.
 */
export const mergeFolderPlan = ({
  pending,
  loosePdfs,
  incoming,
  existingStems,
  existingPdfStems,
}: IMergeFolderInput): IMergedPlan => {
  const parts = [...pending, ...incoming];
  const withRecognition = new Set<string>();
  const withPdf = new Set<string>();
  for (const { path } of parts) {
    const part = classify(baseName(path));
    if (part) (part.role === 'pdf' ? withPdf : withRecognition).add(part.stem);
  }

  const taken = new Set<string>();
  const consumed = loosePdfs.filter((file) => {
    const part = classify(file.name);
    if (!part || !withRecognition.has(part.stem) || withPdf.has(part.stem)) return false;
    if (taken.has(part.stem)) return false;
    taken.add(part.stem);
    return true;
  });

  // Пакет с таким именем уже в проекте — это «уже в проекте», а не повторная загрузка.
  const attachable = new Set([...existingPdfStems].filter((stem) => !existingStems.has(stem)));
  const { plan, incomplete, attachToExisting } = planEntries(
    [...parts, ...consumed.map((file) => ({ file, path: file.name }))],
    attachable,
  );

  const isExisting = (stem: string): boolean => existingStems.has(stemKey(stem));
  return {
    packages: plan.packages,
    plainFiles: plan.plainFiles,
    warnings: plan.warnings.filter((warning) => !isExisting(warning.stem)),
    skipped: plan.skipped,
    pending: [...incomplete].filter(([stem]) => !isExisting(stem)).flatMap(([, list]) => list),
    consumed,
    alreadyInProject: plan.warnings.map((warning) => warning.stem).filter(isExisting),
    attachToExisting,
  };
};

/** Файлы из `<input webkitdirectory>`: путь берётся из webkitRelativePath. */
export const entriesFromInput = (files: readonly File[]): IFolderEntry[] =>
  files.map((file) => ({ file, path: file.webkitRelativePath || file.name }));
