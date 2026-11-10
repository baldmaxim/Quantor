'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useState, type FC } from 'react';

import { Button, cx } from '@/components/ui';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import { useStoredFlag } from '@/lib/cad/useStoredFlag';
import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadJobList } from '@/components/cad/CadJobList';
import { CadSheetPicker } from '@/components/cad/CadSheetPicker';
import { CadSourcePicker } from '@/components/cad/CadSourcePicker';
import { CadTabs, type ICadTab } from '@/components/cad/CadTabs';
import {
  parseSelection,
  selectionQuery,
  withJob,
  withJobView,
  withRevision,
  withView,
  type ICadSelection,
} from '@/lib/cad/selection';

type LeftTab = 'sheets' | 'jobs';

const LEFT_TABS: readonly ICadTab<LeftTab>[] = [
  { id: 'sheets', label: 'Листы' },
  { id: 'jobs', label: 'Задания' },
];

interface ICadScreenProps {
  projectId: string;
}

/** Ключ localStorage: левая колонка (источник, листы, задания) свёрнута при открытом виде. */
const LEFT_COLLAPSED_KEY = 'quantor.cad.left-collapsed';

/**
 * Экран PDF → CAD: выбор источника слева, ход и результат выбранного задания справа.
 *
 * На широком экране (от 1024 px) страница занимает область под шапкой целиком и не
 * прокручивается: прокручиваются только блоки внутри. Когда открыт вид листа, чертёж получает
 * всю правую часть, а левая колонка сужается и сворачивается в полосу.
 */
export const CadScreen: FC<ICadScreenProps> = ({ projectId }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selection = parseSelection(searchParams);
  // Вкладка живёт только в состоянии: в адрес не пишем, чтобы ссылка не меняла раскладку.
  const [leftTab, setLeftTab] = useState<LeftTab>('sheets');
  const [leftCollapsed, setLeftCollapsed] = useStoredFlag(LEFT_COLLAPSED_KEY);
  const viewOpen = Boolean(selection.revision && selection.job) && selection.page !== null;
  const collapsed = viewOpen && leftCollapsed;

  // replace, а не push: переключение вида не должно засорять историю браузера.
  const navigate = (next: ICadSelection) => {
    const query = selectionQuery(next);
    router.replace(`/projects/${projectId}/cad${query ? `?${query}` : ''}`, { scroll: false });
  };

  return (
    <div
      className={cx(
        'mx-auto grid w-full items-start gap-[var(--s-6)]',
        'lg:min-h-0 lg:flex-1 lg:grid-rows-[minmax(0,1fr)] lg:items-stretch',
        !viewOpen && 'max-w-[1400px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)]',
        viewOpen && !collapsed && 'lg:grid-cols-[clamp(260px,22vw,340px)_minmax(0,1fr)]',
        collapsed && 'lg:grid-cols-[44px_minmax(0,1fr)]',
      )}
    >
      <div
        className={cx(
          'flex min-w-0 flex-col gap-[var(--s-6)] lg:min-h-0 lg:overflow-auto lg:overscroll-contain',
          collapsed && 'lg:hidden',
        )}
      >
        {viewOpen && (
          <div className="flex justify-end max-lg:hidden">
            <Button
              iconOnly
              variant="ghost"
              onClick={() => setLeftCollapsed(true)}
              aria-expanded="true"
              aria-label="Свернуть колонку источника и листов"
              title="Свернуть колонку источника и листов"
            >
              <IconChevronLeft width={16} height={16} />
            </Button>
          </div>
        )}
        <CadSourcePicker
          projectId={projectId}
          selectedRevisionId={selection.revision}
          onSelect={(revisionId) => navigate(withRevision(revisionId))}
        />
        {selection.revision && (
          <CadTabs
            idPrefix="cad-left"
            label="Листы и задания ревизии"
            tabs={LEFT_TABS}
            active={leftTab}
            onChange={setLeftTab}
          >
            {/* Листы не размонтируются при переключении: иначе сбросится выбор отмеченных. */}
            <div hidden={leftTab !== 'sheets'}>
              <CadSheetPicker
                // Ключ по ревизии: выбор листов другого документа не переиспользуется.
                key={`sheets:${selection.revision}`}
                projectId={projectId}
                revisionId={selection.revision}
                onJobCreated={(jobId) => navigate(withJob(selection, jobId))}
                openJobId={selection.job}
                openPage={selection.page}
                onOpenResult={(jobId, page, view) =>
                  navigate(withJobView(selection, jobId, page, view))
                }
              />
            </div>
            {leftTab === 'jobs' && (
              <CadJobList
                // Ключ по ревизии: список другого документа не переиспользуется.
                key={selection.revision}
                projectId={projectId}
                revisionId={selection.revision}
                selectedJobId={selection.job}
                onSelect={(jobId) => navigate(withJob(selection, jobId))}
              />
            )}
          </CadTabs>
        )}
      </div>

      {collapsed && (
        <div
          data-testid="cad-left-collapsed"
          className="hidden flex-col items-center rounded-[var(--radius-md)] border border-border-strong bg-surface py-[var(--s-3)] lg:flex"
        >
          <Button
            iconOnly
            variant="ghost"
            onClick={() => setLeftCollapsed(false)}
            aria-expanded="false"
            aria-label="Показать колонку источника и листов"
            title="Показать колонку источника и листов"
          >
            <IconChevronRight width={16} height={16} />
          </Button>
        </div>
      )}

      <div className="min-w-0 lg:min-h-0">
        {selection.revision && selection.job ? (
          <CadJobDetail
            key={`${selection.revision}:${selection.job}`}
            projectId={projectId}
            revisionId={selection.revision}
            jobId={selection.job}
            selectedPage={selection.page}
            selectedView={selection.view}
            onSelectView={(page, view) => navigate(withView(selection, page, view))}
            onJobCreated={(jobId) => navigate(withJob(selection, jobId))}
          />
        ) : (
          <p className="rounded-[var(--radius-md)] border border-dashed border-border-strong px-[var(--s-6)] py-[var(--s-7)] text-center text-sm text-muted">
            Загрузите PDF или выберите документ проекта, затем отметьте откалиброванные листы и
            запустите преобразование.
          </p>
        )}
      </div>
    </div>
  );
};
