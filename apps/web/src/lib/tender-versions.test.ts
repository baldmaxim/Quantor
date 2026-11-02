import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import {
  HASH_PREVIEW_LENGTH,
  TENDER_VERSIONS_FEATURE,
  defaultVersionId,
  formatDeadline,
  hashStart,
  invalidationAfterDelete,
  versionKeys,
  versionTitle,
  versionsAccess,
} from './tender-versions';

describe('доступ к версиям тендера', () => {
  it('пока мета не пришла, решения нет', () => {
    expect(versionsAccess(false, { [TENDER_VERSIONS_FEATURE]: true })).toBe('pending');
  });

  it('открыт только флагом tender.versions', () => {
    expect(versionsAccess(true, { [TENDER_VERSIONS_FEATURE]: true })).toBe('open');
    expect(versionsAccess(true, { [TENDER_VERSIONS_FEATURE]: false })).toBe('hidden');
    expect(versionsAccess(true, { 'calc.portal': true })).toBe('hidden');
  });
});

describe('выбор версии по умолчанию', () => {
  const frozen = (id: string, number: number) => ({ id, number, status: 'frozen' as const });

  it('черновик важнее любой замороженной', () => {
    const versions = [{ id: 'd', number: 3, status: 'draft' as const }, frozen('f', 4)];

    expect(defaultVersionId(versions)).toBe('d');
  });

  it('без черновика — самая новая версия, независимо от порядка списка', () => {
    expect(defaultVersionId([frozen('a', 1), frozen('c', 3), frozen('b', 2)])).toBe('c');
  });

  it('у проекта без версий выбирать нечего', () => {
    expect(defaultVersionId([])).toBeNull();
  });
});

describe('подписи', () => {
  it('подпись версии добавляется после номера', () => {
    expect(versionTitle({ number: 2, label: null })).toBe('Версия 2');
    expect(versionTitle({ number: 2, label: 'после экспертизы' })).toBe(
      'Версия 2 · после экспертизы',
    );
  });

  it('отпечаток показывается началом, а незамороженный — прочерком', () => {
    const hash = 'a'.repeat(64);

    expect(hashStart(hash)).toBe(`${'a'.repeat(HASH_PREVIEW_LENGTH)}…`);
    expect(hashStart(null)).toBe('—');
  });

  it('срок подачи: нечитаемое значение остаётся как есть', () => {
    expect(formatDeadline(null)).toBe('без срока');
    expect(formatDeadline('скоро')).toBe('скоро');
    expect(formatDeadline('2026-12-01')).toContain('2026');
  });
});

describe('сброс запросов после удаления версии', () => {
  it('удалённая версия не перезапрашивается, остальные сбрасываются', async () => {
    const client = new QueryClient();
    const deleted = versionKeys.one('p1', 'v1');
    const other = versionKeys.one('p1', 'v2');
    const list = versionKeys.list('p1');
    const foreign = versionKeys.list('p2');
    [deleted, other, list, foreign].forEach((key) => client.setQueryData(key, []));

    await client.invalidateQueries(invalidationAfterDelete('p1', 'v1'));

    expect(client.getQueryState(deleted)?.isInvalidated).toBe(false);
    expect(client.getQueryState(other)?.isInvalidated).toBe(true);
    expect(client.getQueryState(list)?.isInvalidated).toBe(true);
    expect(client.getQueryState(foreign)?.isInvalidated).toBe(false);
  });
});
