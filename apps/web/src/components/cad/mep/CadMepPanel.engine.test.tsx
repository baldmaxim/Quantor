import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { IWorkspaceCadMep } from '@/components/workspace/cad/types';

import { CadMepPanel } from './CadMepPanel';

const mep = (patch: Partial<IWorkspaceCadMep> = {}): IWorkspaceCadMep => ({
  parent: {
    projectId: 'p1',
    revisionId: 'r1',
    jobId: 'job-parent',
    attempt: 2,
    pageIndex: 80,
    view: 1,
  },
  approval: null,
  revokedDecisions: [],
  routeJobs: [],
  route: null,
  openRemarks: 0,
  onSelectRoute: vi.fn(),
  ...patch,
});

const mount = (value: IWorkspaceCadMep, risers?: ReactNode) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CadMepPanel {...value} risers={risers} />
    </QueryClientProvider>,
  );

describe('вкладка «Трассы» за флагом cad.mep_engine', () => {
  it('флаг открыт: одобрение, построение, список трасс и спецификация', () => {
    mount(mep());
    expect(screen.getByText('1. Одобрение вида')).toBeInTheDocument();
    expect(screen.getByText('2. Построить трассы, ЭОМ и СС')).toBeInTheDocument();
    expect(screen.getByText('3. Трассы вида')).toBeInTheDocument();
    expect(screen.getByText('4. Спецификация')).toBeInTheDocument();
  });

  it('флаг закрыт: остаётся одобрение вида, построения трасс нет', () => {
    mount(mep({ engineRoutes: false }));
    expect(screen.getByText('1. Одобрение вида')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Одобрить вид' })).toBeInTheDocument();
    expect(screen.queryByText('2. Построить трассы, ЭОМ и СС')).toBeNull();
    expect(screen.queryByText('3. Трассы вида')).toBeNull();
    expect(screen.queryByText('4. Спецификация')).toBeNull();
  });

  it('реестр стояков: свёрнутый блок в шаге построения, перед самим построением', () => {
    mount(mep(), <p>реестр стояков</p>);
    const summary = screen.getByText('Реестр стояков по ИОС — вход построения');
    const details = summary.closest('details');
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute('open');
    expect(details).toHaveTextContent('реестр стояков');
    const title = screen.getByText('2. Построить трассы, ЭОМ и СС');
    const build = screen.getByText('Трассы строятся только по одобренному виду.');
    expect(title.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.compareDocumentPosition(build) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('флаг закрыт: реестра стояков нет - строить по нему нечего', () => {
    mount(mep({ engineRoutes: false }), <p>реестр стояков</p>);
    expect(screen.queryByText('реестр стояков')).toBeNull();
    expect(screen.queryByText(/Реестр стояков по ИОС/)).toBeNull();
  });
});
