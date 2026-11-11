import { extensionOf, isAccepted } from '@/lib/upload';

/**
 * Разбор папки, распакованной из ZIP распознанного пакета legacy-v1.
 *
 * Сервер принимает пакет только ZIP-файлом, поэтому папку приходится собирать обратно.
 * Эта функция только решает, что с чем сложить; сам архив собирает buildPackageZip.
 *
 * Комплект по stem: `<stem>.pdf`, `<stem>_results.md`, `<stem>_results.html`,
 * `<stem>_blocks.json`. Подпапки не важны (markdown/, attachments/, data/ и т.п.),
 * регистр расширений тоже.
 */

export interface IFolderEntry {
  readonly file: File;
  /** Путь внутри выбранной папки; для файла без папки — просто имя. */
  readonly path: string;
}

export interface IFolderPackage {
  readonly stem: string;
  readonly pdf: File;
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

export const planFolderUpload = (entries: readonly IFolderEntry[]): IFolderPlan => {
  const groups = new Map<string, Partial<Record<Role, File>>>();
  const plainFiles: File[] = [];
  let skipped = 0;

  // Порядок по пути: результат не зависит от того, в каком порядке браузер отдал файлы.
  const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path, 'ru'));

  for (const { file, path } of sorted) {
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

  for (const [stem, group] of groups) {
    const { pdf, resultsMd, resultsHtml, blocks } = group;
    const hasRecognition = Boolean(resultsMd ?? resultsHtml ?? blocks);

    if (pdf && resultsMd && resultsHtml && blocks) {
      packages.push({ stem, pdf, resultsMd, resultsHtml, blocks });
    } else if (pdf && !hasRecognition) {
      plainFiles.push(pdf);
    } else {
      warnings.push({
        stem,
        missing: ROLE_ORDER.filter((role) => !group[role]).map((role) => roleFileName(stem, role)),
      });
    }
  }

  return { packages, plainFiles, warnings, skipped };
};

/** Файлы из `<input webkitdirectory>`: путь берётся из webkitRelativePath. */
export const entriesFromInput = (files: readonly File[]): IFolderEntry[] =>
  files.map((file) => ({ file, path: file.webkitRelativePath || file.name }));
