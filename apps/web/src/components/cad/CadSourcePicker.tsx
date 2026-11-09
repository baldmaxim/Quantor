'use client';

import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FC } from 'react';

import { CadPdfDropzone } from '@/components/cad/CadPdfDropzone';
import { Button, ProgressRow, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { useStartCadJob } from '@/lib/cad/queries';
import { errorMessage } from '@/lib/errors';
import { formatBytes } from '@/lib/format';
import { useDocumentsRevisions, useProjectDocuments } from '@/lib/queries';
import { UploadError, extensionOf, uploadFile } from '@/lib/upload';

interface ICadSourcePickerProps {
  projectId: string;
  selectedRevisionId: string | null;
  /** Ревизия и задание выбраны (запущены или найдены идущие). */
  onSelect: (revisionId: string, jobId: string) => void;
}

interface IUploadState {
  readonly name: string;
  readonly fraction: number | null;
}

/**
 * Выбор исходного PDF: загрузка нового или одна из ревизий проекта.
 * После выбора запускается преобразование (страницы выбирает движок); если у ревизии уже
 * есть идущее задание, выбирается оно.
 */
export const CadSourcePicker: FC<ICadSourcePickerProps> = ({
  projectId,
  selectedRevisionId,
  onSelect,
}) => {
  const client = useQueryClient();
  const documents = useProjectDocuments(projectId);
  const pdfs = (documents.data?.items ?? []).filter((item) => item.document_kind === 'pdf');
  const revisions = useDocumentsRevisions(pdfs.map((item) => item.id));
  const start = useStartCadJob(projectId);

  const [upload, setUpload] = useState<IUploadState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  // Синхронная защита от повторного запуска: состояние `busy` обновляется после рендера, и два
  // быстрых нажатия успевают запустить два задания или две загрузки.
  const launching = useRef(false);
  const uploading = useRef(false);

  useEffect(() => () => controller.current?.abort(), []);

  const busy = upload !== null || start.isPending;

  const launch = async (revisionId: string) => {
    if (launching.current) return;
    launching.current = true;
    setProblem(null);
    try {
      const jobId = await start.mutateAsync({ revisionId });
      onSelect(revisionId, jobId);
    } catch (error) {
      setProblem(cadErrorText(error));
    } finally {
      launching.current = false;
    }
  };

  const handleFile = async (file: File) => {
    if (uploading.current) return;
    setNotice(null);
    setProblem(null);
    if (extensionOf(file.name) !== 'pdf') {
      setProblem('Нужен файл PDF.');
      return;
    }
    uploading.current = true;
    controller.current = new AbortController();
    setUpload({ name: file.name, fraction: 0 });
    try {
      const result = await uploadFile({
        projectId,
        file,
        signal: controller.current.signal,
        onProgress: ({ fraction }) => setUpload({ name: file.name, fraction }),
      });
      await client.invalidateQueries({ queryKey: ['project', projectId] });
      await client.invalidateQueries({ queryKey: ['document', result.document.id] });
      if (result.is_duplicate) {
        setNotice('Такой PDF уже загружен в проект: используется существующая ревизия.');
      }
      setUpload(null);
      uploading.current = false;
      await launch(result.revision.id);
    } catch (error) {
      setUpload(null);
      uploading.current = false;
      if (error instanceof DOMException && error.name === 'AbortError') return;
      const code = error instanceof UploadError ? error.code : 'NETWORK_ERROR';
      setProblem(errorMessage(code, error instanceof Error ? error.message : undefined));
    }
  };

  return (
    <section className="flex flex-col gap-[var(--s-5)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
      <h2 className="text-sm font-medium">Исходный PDF</h2>

      <CadPdfDropzone disabled={busy} onPick={(file) => void handleFile(file)} />

      {upload && <ProgressRow value={upload.fraction} label={`Загрузка ${upload.name}`} />}
      {notice && <p className="text-xs text-muted">{notice}</p>}
      {problem && (
        <p role="alert" className="text-xs text-danger">
          {problem}
        </p>
      )}

      <div className="flex flex-col gap-[var(--s-3)]">
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          PDF проекта
        </h3>
        {documents.isPending || revisions.isPending ? (
          <SkeletonRows rows={3} />
        ) : documents.isError ? (
          <p className="text-xs text-danger">Не удалось прочитать список документов.</p>
        ) : pdfs.length === 0 ? (
          <p className="text-xs text-muted">В проекте нет PDF-документов.</p>
        ) : (
          <ul className="flex flex-col rounded-[var(--radius-md)] border border-border">
            {pdfs.map((document) => (
              <PdfRow
                key={document.id}
                document={document}
                revision={revisions.byDocument.get(document.id)?.items.at(-1) ?? null}
                selectedRevisionId={selectedRevisionId}
                disabled={busy}
                onLaunch={(revisionId) => void launch(revisionId)}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

interface IPdfRowProps {
  document: DocumentRead;
  revision: DocumentRevisionRead | null;
  selectedRevisionId: string | null;
  disabled: boolean;
  onLaunch: (revisionId: string) => void;
}

const PdfRow: FC<IPdfRowProps> = ({
  document,
  revision,
  selectedRevisionId,
  disabled,
  onLaunch,
}) => {
  const selected = revision !== null && revision.id === selectedRevisionId;

  return (
    <li
      className={cx(
        'flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0',
        selected && 'bg-accent-soft',
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-[var(--s-1)]">
        <span className="text-sm [overflow-wrap:anywhere]" title={document.display_name}>
          {document.display_name}
        </span>
        {revision ? (
          <span className="mono text-xs text-muted">
            последняя ревизия · {formatBytes(revision.source_size)}
          </span>
        ) : (
          <span className="text-xs text-muted">Ревизий нет</span>
        )}
      </span>
      {selected ? (
        <StatusBadge tone="accent" dot={false}>
          выбран
        </StatusBadge>
      ) : (
        <Button
          compact
          disabled={disabled || revision === null}
          onClick={() => revision && onLaunch(revision.id)}
          className="max-md:h-[44px]"
        >
          Выбрать
        </Button>
      )}
    </li>
  );
};
