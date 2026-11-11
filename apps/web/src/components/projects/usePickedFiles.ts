'use client';

import { useState } from 'react';

import { classifyFiles, packagePicked, type PickedFile } from '@/components/projects/FileDropzone';
import type { FolderReportData } from '@/components/projects/FolderReport';
import { extensionOf } from '@/lib/upload';
import { mergeFolderPlan, type IFolderEntry } from '@/lib/uploads/packageFolder';

/**
 * Выбранные файлы окна загрузки и комплекты распознавания, собираемые из нескольких выборов.
 *
 * Распознавалка кладёт PDF и результаты в разные папки, поэтому комплект может собираться
 * из двух добавлений в любом порядке. Неполные комплекты ждут в `pending`; каждое новое
 * добавление планируется заново вместе с ними (чистая логика — `mergeFolderPlan`).
 */

interface IPickState {
  readonly files: readonly PickedFile[];
  readonly pending: readonly IFolderEntry[];
  readonly report: FolderReportData | null;
}

const EMPTY: IPickState = { files: [], pending: [], report: null };

/** Обычный (не пакет из папки) PDF, ещё не загруженный: может достроить комплект. */
const loosePdfsOf = (files: readonly PickedFile[]): File[] =>
  files.flatMap((picked) =>
    picked.accepted && picked.file instanceof File && extensionOf(picked.file.name) === 'pdf'
      ? [picked.file]
      : [],
  );

const unique = (values: readonly string[]): string[] => Array.from(new Set(values));

const merge = (
  state: IPickState,
  incoming: readonly IFolderEntry[],
  rest: readonly File[],
  existingStems: ReadonlySet<string>,
): IPickState => {
  const plan = mergeFolderPlan({
    pending: state.pending,
    loosePdfs: loosePdfsOf(state.files),
    incoming,
    existingStems,
  });
  const added = [...plan.packages.map(packagePicked), ...classifyFiles(plan.plainFiles)];
  const kept = state.files.filter(
    (picked) => !(picked.file instanceof File && plan.consumed.includes(picked.file)),
  );

  return {
    files: [...kept, ...added, ...classifyFiles(rest)],
    pending: plan.pending,
    report: {
      warnings: plan.warnings,
      skipped: (state.report?.skipped ?? 0) + plan.skipped,
      added: added.length,
      alreadyInProject: unique([
        ...(state.report?.alreadyInProject ?? []),
        ...plan.alreadyInProject,
      ]),
    },
  };
};

export const usePickedFiles = (existingStems: ReadonlySet<string>) => {
  const [state, setState] = useState<IPickState>(EMPTY);

  /** Папка выбрана или брошена. */
  const addFolder = (entries: readonly IFolderEntry[]): void =>
    setState((current) => merge(current, entries, [], existingStems));

  /** Отдельные файлы; PDF достраивают ожидающие комплекты, остальное — как раньше. */
  const addFiles = (files: readonly File[]): void =>
    setState((current) => {
      if (current.pending.length === 0) {
        return { ...current, files: [...current.files, ...classifyFiles(files)] };
      }
      const pdfs = files.filter((file) => extensionOf(file.name) === 'pdf');
      const rest = files.filter((file) => extensionOf(file.name) !== 'pdf');
      return merge(
        current,
        pdfs.map((file) => ({ file, path: file.name })),
        rest,
        existingStems,
      );
    });

  const removeAt = (index: number): void =>
    setState((current) => ({ ...current, files: current.files.filter((_, i) => i !== index) }));

  /** Загруженный файл уходит из списка выбранных; упавшие остаются для повтора. */
  const removeDone = (done: PickedFile['file']): void =>
    setState((current) => ({
      ...current,
      files: current.files.filter((picked) => picked.file !== done),
    }));

  const reset = (): void => setState(EMPTY);

  return {
    files: state.files,
    folderReport: state.report,
    addFolder,
    addFiles,
    removeAt,
    removeDone,
    reset,
  };
};
