import type { CadStylePreviewResult, CadStyleVersionRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadStylePanel } from './CadStylePanel';
import type { IWorkspaceCadStyle } from './types';

const version: CadStyleVersionRead = {
  version: 3,
  title: 'Том 1',
  style: {},
  sha256: 'abc',
  source: { kind: 'samples', page_index: 4 },
  created_at: '2026-11-16T10:00:00Z',
  created_by: null,
};

const previewBody = (over: Record<string, unknown> = {}) => ({
  classes: {
    monolith: { grays: [0.5], fills: 12, area_pt2: 100, area_m2: null },
    shaft: { grays: [0.7], fills: 3, area_pt2: 20, area_m2: 1.5 },
    masonry: { grays: [0.3], hatch_segments: 40 },
    door: { pen_max_width: 0.35, candidates_not_doors: 7 },
  },
  field_sources: { monolith_fill_gray: 'samples', shaft_fill_gray: 'base:default' },
  unclassified_fill_share: null,
  rejected_samples: [],
  unsupported_samples: [],
  warnings: [],
  ...over,
});

const result = (over: Partial<CadStylePreviewResult> = {}): CadStylePreviewResult => ({
  base_version: null,
  engine_version: null,
  mm_per_pt: null,
  page_index: 0,
  preview: previewBody(),
  profile: {},
  reasons: [],
  result_status: 'profile',
  revision_id: 'rev',
  scale_source: 'none',
  ...over,
});

const props = (over: Partial<IWorkspaceCadStyle> = {}): IWorkspaceCadStyle => ({
  status: 'ready',
  current: null,
  loadError: null,
  refreshError: null,
  onReload: vi.fn(),
  sampling: true,
  startDisabledReason: null,
  onStartSampling: vi.fn(),
  onStopSampling: vi.fn(),
  activeClass: 'monolith',
  onClassChange: vi.fn(),
  negative: false,
  onNegativeChange: vi.fn(),
  samples: [],
  onRemoveSample: vi.fn(),
  onClearSamples: vi.fn(),
  preview: null,
  onPreview: vi.fn(),
  accepting: false,
  onAccept: vi.fn(),
  acceptError: null,
  savedVersion: null,
  ...over,
});

describe('CadStylePanel', () => {
  it('нет профиля: подсказка и кнопка «Снять по образцам»', () => {
    const onStartSampling = vi.fn();
    render(<CadStylePanel {...props({ sampling: false, onStartSampling })} />);
    expect(screen.getByText(/Профиль не задан/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Снять по образцам' }));
    expect(onStartSampling).toHaveBeenCalled();
  });

  it('есть профиль: версия, название и источник', () => {
    render(<CadStylePanel {...props({ sampling: false, current: version })} />);
    expect(screen.getByText(/Версия 3 · Том 1/)).toBeTruthy();
    expect(screen.getByText(/по образцам, лист 5/)).toBeTruthy();
  });

  it('режим образцов: пометка у классов без поля и отрицательный образец', () => {
    const onNegativeChange = vi.fn();
    render(<CadStylePanel {...props({ activeClass: 'insulation', onNegativeChange })} />);
    expect(screen.getByText(/Утеплитель: движок пока не учитывает/)).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', { name: /Это НЕ утеплитель/ }));
    expect(onNegativeChange).toHaveBeenCalledWith(true);
  });

  it('список образцов: удалить и очистить всё', () => {
    const onRemoveSample = vi.fn();
    const onClearSamples = vi.fn();
    render(
      <CadStylePanel
        {...props({
          samples: [
            { class: 'monolith', x: 0.1, y: 0.1, negative: false },
            { class: 'door', x: 0.2, y: 0.2, negative: true },
          ],
          onRemoveSample,
          onClearSamples,
        })}
      />,
    );
    expect(screen.getByText('Образцы: 2 из 200')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Удалить образец: Дверь (не) №1' }));
    expect(onRemoveSample).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole('button', { name: 'Очистить всё' }));
    expect(onClearSamples).toHaveBeenCalled();
  });

  it('предпросмотр: null-площадь - «не определена», не ноль; доля «—»', () => {
    render(
      <CadStylePanel {...props({ preview: { running: false, result: result(), error: null } })} />,
    );
    const region = screen.getByRole('region', { name: 'Найдено на листе' });
    expect(region.textContent).toContain('площадь не определена: нет масштаба листа');
    expect(region.textContent).toContain('1,5 м²');
    expect(region.textContent).toContain('Масштаб: не определён');
    expect(region.textContent).toContain('Неразобранные заливки: —');
    expect(region.textContent).not.toMatch(/\b0 м²/);
    expect(screen.getByRole('region', { name: 'Источники полей' }).textContent).toContain(
      'из основы',
    );
  });

  it('no_signature: подсказка про щелчки, принять нельзя', () => {
    render(
      <CadStylePanel
        {...props({
          preview: {
            running: false,
            result: result({
              result_status: 'no_signature',
              profile: null,
              preview: previewBody({ classes: null, field_sources: null }),
            }),
            error: null,
          },
        })}
      />,
    );
    expect(screen.getByText(/щёлкайте внутри заливок и по штриховке/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Принять' })).toBeNull();
  });

  it('profile_out_of_limits: причины, принять нельзя', () => {
    render(
      <CadStylePanel
        {...props({
          preview: {
            running: false,
            result: result({
              result_status: 'profile_out_of_limits',
              profile: null,
              reasons: ['слишком широкое перо двери'],
            }),
            error: null,
          },
        })}
      />,
    );
    expect(screen.getByText('слишком широкое перо двери')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Принять' })).toBeNull();
  });

  it('отклонённые щелчки: причина по-русски', () => {
    render(
      <CadStylePanel
        {...props({
          samples: [{ class: 'monolith', x: 0.1, y: 0.1, negative: false }],
          preview: {
            running: false,
            result: result({
              preview: previewBody({
                rejected_samples: [
                  {
                    sample: { index: 0, class: 'monolith', x: 0.1, y: 0.1, negative: false },
                    reason: 'no_fill_at_point',
                  },
                ],
              }),
            }),
            error: null,
          },
        })}
      />,
    );
    const rejected = screen.getByRole('region', { name: 'Отклонённые щелчки' });
    expect(rejected.textContent).toContain('Монолит №1: в точке нет заливки');
  });

  it('«Принять» отдаёт название версии; при отказе (конфликт) заблокирована', () => {
    const onAccept = vi.fn();
    const base = props({ onAccept, preview: { running: false, result: result(), error: null } });
    const { rerender } = render(<CadStylePanel {...base} />);
    fireEvent.change(screen.getByLabelText('Название версии'), { target: { value: 'Том 2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Принять' }));
    expect(onAccept).toHaveBeenCalledWith('Том 2');

    rerender(<CadStylePanel {...base} acceptError="Профиль изменился" />);
    expect((screen.getByRole('button', { name: 'Принять' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getByRole('alert').textContent).toContain('Профиль изменился');
  });

  it('сохранённая версия: сообщение про повторное преобразование', () => {
    render(<CadStylePanel {...props({ sampling: false, savedVersion: 4 })} />);
    expect(screen.getByRole('status').textContent).toContain(
      'Версия 4 сохранена. Преобразуйте листы тома заново, чтобы применить профиль.',
    );
  });

  it('отклонённый щелчок нумеруется внутри класса, у отрицательного «(не)»', () => {
    const samples = [
      { class: 'monolith' as const, x: 0.1, y: 0.1, negative: false },
      { class: 'door' as const, x: 0.2, y: 0.2, negative: false },
      { class: 'monolith' as const, x: 0.3, y: 0.3, negative: true },
    ];
    render(
      <CadStylePanel
        {...props({
          samples,
          preview: {
            running: false,
            result: result({
              preview: previewBody({
                rejected_samples: [
                  {
                    sample: { index: 2, class: 'monolith', x: 0.3, y: 0.3, negative: true },
                    reason: 'no_fill_at_point',
                  },
                ],
              }),
            }),
            error: null,
          },
        })}
      />,
    );
    expect(screen.getByRole('region', { name: 'Отклонённые щелчки' }).textContent).toContain(
      'Монолит (не) №2: в точке нет заливки',
    );
  });

  it('неразобранный предпросмотр принять нельзя', () => {
    render(
      <CadStylePanel
        {...props({
          preview: { running: false, result: result({ preview: { broken: true } }), error: null },
        })}
      />,
    );
    expect(screen.getByText(/Предпросмотр не разобран/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Принять' })).toBeNull();
  });

  it('класс без серых: «серый класса не задан», не нули; перо в pt', () => {
    render(
      <CadStylePanel
        {...props({
          preview: {
            running: false,
            result: result({
              preview: previewBody({
                classes: {
                  monolith: { grays: [], fills: 0, area_pt2: 0, area_m2: null },
                  shaft: { grays: [0.7], fills: 3, area_pt2: 20, area_m2: 1.5 },
                  masonry: { grays: [], hatch_segments: 0 },
                  door: { pen_max_width: 0.35, candidates_not_doors: 7 },
                },
              }),
            }),
            error: null,
          },
        })}
      />,
    );
    const text = screen.getByRole('region', { name: 'Найдено на листе' }).textContent ?? '';
    expect(text).toContain('Монолит: серый класса не задан');
    expect(text).toContain('Кладка: серый класса не задан');
    expect(text).not.toContain('0 заливок');
    expect(text).toContain('0.35 pt');
  });

  it('ошибка перечитывания при загруженном профиле - баннер, режим остаётся', () => {
    const onReload = vi.fn();
    render(<CadStylePanel {...props({ current: version, refreshError: 'сеть', onReload })} />);
    expect(screen.getByRole('alert').textContent).toContain('сеть');
    expect(screen.getByRole('button', { name: 'Предпросмотр' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onReload).toHaveBeenCalled();
  });

  it('идёт принятие: удаление образцов и очистка неактивны', () => {
    render(
      <CadStylePanel
        {...props({
          accepting: true,
          samples: [{ class: 'monolith', x: 0.1, y: 0.1, negative: false }],
          preview: { running: false, result: result(), error: null },
        })}
      />,
    );
    expect((screen.getByRole('button', { name: /Удалить образец/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Очистить всё' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
