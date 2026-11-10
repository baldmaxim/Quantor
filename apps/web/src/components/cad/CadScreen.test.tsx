import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetStoredFlags } from '@/lib/cad/useStoredFlag';

const nav = vi.hoisted(() => ({ query: '' }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.query),
}));
vi.mock('@/components/cad/CadSourcePicker', () => ({ CadSourcePicker: () => <p>источник</p> }));
vi.mock('@/components/cad/CadSheetPicker', () => ({ CadSheetPicker: () => <p>листы</p> }));
vi.mock('@/components/cad/CadJobList', () => ({ CadJobList: () => <p>задания</p> }));
vi.mock('@/components/cad/CadJobDetail', () => ({ CadJobDetail: () => <p>задание справа</p> }));

import { CadScreen } from './CadScreen';

const REVISION = '11111111-1111-4111-8111-111111111111';
const JOB = '22222222-2222-4222-8222-222222222222';
const KEY = 'quantor.cad.left-collapsed';

const root = () => screen.getByText('источник').closest('div[class*="grid"]') as HTMLElement;

beforeEach(() => {
  window.localStorage.clear();
  resetStoredFlags();
  nav.query = '';
});

describe('CadScreen: раскладка', () => {
  it('вид не открыт: две колонки, кнопки свёртывания нет', () => {
    nav.query = `revision=${REVISION}&job=${JOB}`;
    render(<CadScreen projectId="p1" />);
    expect(screen.queryByRole('button', { name: /Свернуть колонку/ })).toBeNull();
    expect(root().className).toContain('lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)]');
    expect(root().className).toContain('max-w-[1400px]');
  });

  it('вид открыт: левая колонка узкая, чертёж получает остальное, ширина не ограничена', () => {
    nav.query = `revision=${REVISION}&job=${JOB}&page=0&view=1`;
    render(<CadScreen projectId="p1" />);
    expect(root().className).toContain('lg:grid-cols-[clamp(260px,22vw,340px)_minmax(0,1fr)]');
    expect(root().className).not.toContain('max-w-[1400px]');
    // страница не прокручивается, блоки внутри - да
    expect(root().className).toContain('lg:min-h-0');
  });

  it('левая колонка сворачивается в полосу и возвращается; состояние в localStorage', () => {
    nav.query = `revision=${REVISION}&job=${JOB}&page=0&view=1`;
    render(<CadScreen projectId="p1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть колонку источника и листов' }));
    expect(window.localStorage.getItem(KEY)).toBe('1');
    expect(screen.getByTestId('cad-left-collapsed')).toBeInTheDocument();
    expect(root().className).toContain('lg:grid-cols-[44px_minmax(0,1fr)]');

    fireEvent.click(screen.getByRole('button', { name: 'Показать колонку источника и листов' }));
    expect(window.localStorage.getItem(KEY)).toBe('0');
    expect(screen.queryByTestId('cad-left-collapsed')).toBeNull();
  });

  it('сохранённая свёрнутость не действует, пока вид не открыт', () => {
    window.localStorage.setItem(KEY, '1');
    nav.query = `revision=${REVISION}&job=${JOB}`;
    render(<CadScreen projectId="p1" />);
    expect(screen.queryByTestId('cad-left-collapsed')).toBeNull();
    expect(screen.getByText('источник')).toBeInTheDocument();
  });
});
