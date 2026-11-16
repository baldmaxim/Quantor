'use client';

import type { TenderCalcRead, TenderCalcVersionRead } from '@quantor/api-client';
import { useState, type FC, type ReactNode } from 'react';

import { Button, ErrorState, SkeletonRows, StatusBadge, buttonClassName } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { useHasPermission } from '@/lib/session';
import { TENDER_CALC_WITHDRAW } from '@/lib/tender/access';
import { VERSION_STATUS_LABELS, VERSION_STATUS_TONES, shortSha } from '@/lib/tender/present';
import { tenderCalcPackageUrl, useTenderCalcVersion } from '@/lib/tender/queries';
import { systemLabel } from '@/lib/tender/systems';

import { QuantitiesTable } from './QuantitiesTable';
import { SystemSwatch } from './SystemSwatch';
import { VersionFit } from './VersionFit';
import { VersionNotes } from './VersionNotes';
import { VersionViews } from './VersionViews';
import { WithdrawVersionDialog } from './WithdrawVersionDialog';

/**
 * Карточка версии расчёта: шапка с действиями, объёмы с разницей, вопросы, предупреждения, привязка
 * к осям и виды со ссылками на лист. «Скачать пакет» — ссылка на эндпоинт (cookie сеанса).
 */

interface IDetailProps {
  readonly projectId: string;
  readonly calc: TenderCalcRead;
  readonly versionId: string;
  readonly onBack: () => void;
}

const Section: FC<{ readonly title: string; readonly children: ReactNode }> = ({
  title,
  children,
}) => (
  <section className="flex flex-col gap-[var(--s-4)]">
    <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">{title}</h3>
    {children}
  </section>
);

const Header: FC<{
  readonly projectId: string;
  readonly calc: TenderCalcRead;
  readonly version: TenderCalcVersionRead;
  readonly onWithdraw: () => void;
}> = ({ projectId, calc, version, onWithdraw }) => {
  const canWithdraw = useHasPermission(TENDER_CALC_WITHDRAW);
  const stale = version.views.some((view) => view.base_stale);

  return (
    <div className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)]">
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <SystemSwatch system={calc.system} />
        <span className="text-xs text-muted">{systemLabel(calc.system)}</span>
        <StatusBadge tone={VERSION_STATUS_TONES[version.status]}>
          {VERSION_STATUS_LABELS[version.status]}
        </StatusBadge>
        {stale && <StatusBadge tone="warning">база устарела</StatusBadge>}
      </div>
      <h2 className="text-lg font-semibold [overflow-wrap:anywhere]">
        {version.title} · №{version.number} · {version.label}
      </h2>
      {version.message && <p className="m-0 text-sm [overflow-wrap:anywhere]">{version.message}</p>}
      <p className="m-0 text-xs text-muted">
        {version.author} · {formatWhen(version.uploaded_at)} · база #{version.base_release_number} ·
        sha256 <span className="mono">{shortSha(version.package_sha256)}</span>
        {version.producer.skill ? ` · навык ${version.producer.skill}` : ''}
      </p>
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <a
          href={tenderCalcPackageUrl(projectId, version.id)}
          download
          className={buttonClassName({ variant: 'primary' })}
        >
          Скачать пакет
        </a>
        {canWithdraw && version.status !== 'withdrawn' && (
          <Button variant="danger" onClick={onWithdraw}>
            Отозвать версию
          </Button>
        )}
      </div>
    </div>
  );
};

export const CalcVersionDetail: FC<IDetailProps> = ({ projectId, calc, versionId, onBack }) => {
  const query = useTenderCalcVersion(projectId, versionId);
  const [withdrawing, setWithdrawing] = useState(false);

  return (
    <div className="flex flex-col gap-[var(--s-6)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <Button onClick={onBack}>← История версий</Button>
      </div>
      {query.isPending && <SkeletonRows rows={6} />}
      {query.isError && (
        <ErrorState
          title="Версия не загрузилась"
          code={extractCode(query.error)}
          description={extractMessage(query.error) ?? errorMessage(extractCode(query.error))}
          onRetry={() => void query.refetch()}
        />
      )}
      {query.data && (
        <>
          <Header
            projectId={projectId}
            calc={calc}
            version={query.data}
            onWithdraw={() => setWithdrawing(true)}
          />
          <Section title="Объёмы">
            <QuantitiesTable version={query.data} />
          </Section>
          <Section title="Виды">
            <VersionViews projectId={projectId} calcId={calc.id} views={query.data.views} />
          </Section>
          <VersionNotes version={query.data} />
          <Section title="Привязка к осям">
            <VersionFit fit={query.data.fit} />
          </Section>
          <WithdrawVersionDialog
            projectId={projectId}
            version={query.data}
            open={withdrawing}
            onClose={() => setWithdrawing(false)}
          />
        </>
      )}
    </div>
  );
};
