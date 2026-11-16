import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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

const mount = (value: IWorkspaceCadMep) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CadMepPanel {...value} />
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
});
