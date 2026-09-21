import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  chooseOpenTarget,
  documentOpenState,
  latestOpenableRevision,
  noTargetReason,
  openTargets,
  revisionOpenState,
} from './openability';

/**
 * Открываемость ревизии.
 *
 * Главный случай — обычный PDF: распознавания у него нет и не будет, а открыть его надо.
 * Прежнее условие `processing_status === 'ready'` не давало этого никогда.
 */

const pdf = (id = 'doc-1'): DocumentRead => ({
  id,
  project_id: 'p-1',
  display_name: 'чертёж.pdf',
  discipline: null,
  document_kind: 'pdf',
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
});

const revision = (patch: Partial<DocumentRevisionRead> = {}): DocumentRevisionRead => ({
  id: 'rev-1',
  document_id: 'doc-1',
  revision_label: null,
  source_filename: 'чертёж.pdf',
  source_mime: 'application/pdf',
  source_size: 1024,
  source_sha256: 'a'.repeat(64),
  processing_status: 'unprocessed',
  processing_error_code: null,
  geometry_status: 'ready',
  geometry_error_code: null,
  sheet_count: 2,
  source_metadata: {},
  created_at: '2026-09-01T10:00:00Z',
  ...patch,
});

describe('revisionOpenState', () => {
  it('нераспознанный PDF с готовой геометрией открывается', () => {
    expect(revisionOpenState(pdf(), revision()).kind).toBe('openable');
  });

  it('распознанный пакет остаётся открываемым', () => {
    const state = revisionOpenState(pdf(), revision({ processing_status: 'ready' }));

    expect(state.kind).toBe('openable');
  });

  it('ревизия из пакета без извлечения геометрии открывается по наличию листов', () => {
    const state = revisionOpenState(
      pdf(),
      revision({ processing_status: 'ready', geometry_status: 'not_applicable' }),
    );

    expect(state.kind).toBe('openable');
  });

  it('готовность не выдаётся, пока геометрия в работе', () => {
    expect(revisionOpenState(pdf(), revision({ geometry_status: 'pending' })).kind).toBe(
      'preparing',
    );
    expect(revisionOpenState(pdf(), revision({ geometry_status: 'extracting' })).kind).toBe(
      'preparing',
    );
  });

  it('ошибка геометрии показывается с кодом причины, а не прячется', () => {
    const state = revisionOpenState(
      pdf(),
      revision({ geometry_status: 'failed', geometry_error_code: 'PDF_UNREADABLE' }),
    );

    expect(state).toEqual({ kind: 'geometry_failed', errorCode: 'PDF_UNREADABLE' });
  });

  it('без листов открывать нечего', () => {
    expect(revisionOpenState(pdf(), revision({ sheet_count: 0 })).kind).toBe('no_sheets');
  });

  it('архив и BIM-модель в просмотрщик не идут', () => {
    const archive = { ...pdf(), document_kind: 'recognized_package' as const };

    expect(revisionOpenState(archive, revision()).kind).toBe('not_viewable');
  });
});

describe('latestOpenableRevision', () => {
  it('берёт последнюю открываемую, а не первую', () => {
    const list = [
      revision({ id: 'старая' }),
      revision({ id: 'готовится', geometry_status: 'pending', sheet_count: 0 }),
      revision({ id: 'свежая' }),
    ];

    expect(latestOpenableRevision(pdf(), list)?.id).toBe('свежая');
  });

  it('пропускает неготовую свежую ревизию и возвращает прежнюю готовую', () => {
    const list = [
      revision({ id: 'готовая' }),
      revision({ id: 'ещё-готовится', geometry_status: 'extracting', sheet_count: 0 }),
    ];

    expect(latestOpenableRevision(pdf(), list)?.id).toBe('готовая');
  });

  it('без ревизий ничего не выдумывает', () => {
    expect(latestOpenableRevision(pdf(), [])).toBeNull();
    expect(documentOpenState(pdf(), [])).toBeNull();
  });
});

describe('chooseOpenTarget', () => {
  it('не зависит от порядка списка документов', () => {
    const first = pdf('doc-1');
    const second = pdf('doc-2');
    const older = revision({ id: 'rev-old', created_at: '2026-09-01T10:00:00Z' });
    const newer = revision({ id: 'rev-new', created_at: '2026-09-05T10:00:00Z' });

    const byId = (documentId: string) => (documentId === 'doc-1' ? [older] : [newer]);

    const straight = chooseOpenTarget(openTargets([first, second], byId));
    const reversed = chooseOpenTarget(openTargets([second, first], byId));

    expect(straight?.revision.id).toBe('rev-new');
    expect(reversed?.revision.id).toBe('rev-new');
  });

  it('при совпадении времени выбор всё равно однозначен', () => {
    const same = '2026-09-05T10:00:00Z';
    const a = { document: pdf('doc-1'), revision: revision({ id: 'aaa', created_at: same }) };
    const b = { document: pdf('doc-2'), revision: revision({ id: 'bbb', created_at: same }) };

    expect(chooseOpenTarget([a, b])?.revision.id).toBe('bbb');
    expect(chooseOpenTarget([b, a])?.revision.id).toBe('bbb');
  });

  it('готовый второй документ не теряется из-за неготового первого', () => {
    const waiting = pdf('doc-1');
    const ready = pdf('doc-2');
    const byId = (documentId: string) =>
      documentId === 'doc-1'
        ? [revision({ geometry_status: 'pending', sheet_count: 0 })]
        : [revision({ id: 'rev-ready' })];

    expect(chooseOpenTarget(openTargets([waiting, ready], byId))?.revision.id).toBe('rev-ready');
  });

  it('открывать нечего — честный null', () => {
    expect(chooseOpenTarget([])).toBeNull();
  });
});

describe('noTargetReason', () => {
  it('подготовка важнее прочих причин', () => {
    expect(
      noTargetReason([{ kind: 'geometry_failed', errorCode: null }, { kind: 'preparing' }]),
    ).toContain('Готовим листы');
  });

  it('ошибка подготовки называется прямо', () => {
    expect(noTargetReason([{ kind: 'geometry_failed', errorCode: null }])).toContain(
      'не подготовлены',
    );
  });

  it('пустой проект зовёт загрузить PDF, а не распознанный пакет', () => {
    const reason = noTargetReason([]);

    expect(reason).toContain('Загрузите PDF');
    expect(reason).not.toContain('пакет');
  });
});
