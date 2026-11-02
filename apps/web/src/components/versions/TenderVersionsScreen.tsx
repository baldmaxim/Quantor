'use client';

import { useState } from 'react';

import { CreateDraftDialog } from '@/components/versions/CreateDraftDialog';
import { VersionDetail } from '@/components/versions/VersionDetail';
import { VersionList } from '@/components/versions/VersionList';
import { ErrorState, SkeletonRows } from '@/components/ui';
import { errorMessage, extractCode } from '@/lib/errors';
import { defaultVersionId, useTenderVersion, useTenderVersions } from '@/lib/tender-versions';
import { useDocumentsRevisions, useProject, useProjectDocuments } from '@/lib/queries';

/**
 * Экран «Версии тендера»: список слева, карточка выбранной версии справа; на телефоне друг под
 * другом. Ревизии документов грузятся один раз на экран и обслуживают все строки состава.
 */

export const TenderVersionsScreen = ({ projectId }: { projectId: string }) => {
  const [picked, setPicked] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const project = useProject(projectId);
  const versions = useTenderVersions(projectId, true);
  const documents = useProjectDocuments(projectId);
  const projectDocuments = documents.data?.items ?? [];
  const revisions = useDocumentsRevisions(projectDocuments.map((document) => document.id));

  const list = versions.data ?? [];
  // Выбранная версия могла исчезнуть (черновик удалён): тогда открывается версия по умолчанию.
  const selectedId = list.some((version) => version.id === picked)
    ? picked
    : defaultVersionId(list);
  const selected = useTenderVersion(projectId, selectedId);

  if (versions.isError) {
    return (
      <ErrorState
        title="Версии не загрузились"
        description={errorMessage(extractCode(versions.error))}
        onRetry={() => void versions.refetch()}
      />
    );
  }
  if (!versions.data) return <SkeletonRows rows={5} />;

  return (
    <div className="grid items-start gap-[var(--s-6)] lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      <VersionList
        versions={list}
        selectedId={selectedId}
        hasDraft={list.some((version) => version.status === 'draft')}
        onSelect={setPicked}
        onCreate={() => setCreating(true)}
      />

      {selectedId !== null &&
        (selected.isError ? (
          <ErrorState
            title="Версия не загрузилась"
            description={errorMessage(extractCode(selected.error))}
            onRetry={() => void selected.refetch()}
          />
        ) : selected.data ? (
          <VersionDetail
            key={selected.data.id}
            projectId={projectId}
            version={selected.data}
            projectLinked={project.data?.source === 'tenderhub'}
            projectDocuments={projectDocuments}
            revisionsOf={(documentId) => revisions.byDocument.get(documentId)?.items ?? null}
            onDeleted={() => setPicked(null)}
          />
        ) : (
          <SkeletonRows rows={4} />
        ))}

      <CreateDraftDialog
        open={creating}
        onClose={() => setCreating(false)}
        projectId={projectId}
        onCreated={setPicked}
      />
    </div>
  );
};
