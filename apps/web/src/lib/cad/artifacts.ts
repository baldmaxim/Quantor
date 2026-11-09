import { env } from '../env';

/**
 * Адрес скачивания файла попытки. Файл отдаёт только API после проверки пространства,
 * проекта, ревизии и задания; ключей хранилища и presigned-адресов в интерфейсе нет.
 * Имя — относительное имя артефакта из ответа API (`CadArtifactRead.name`).
 */
export const cadArtifactUrl = (
  projectId: string,
  revisionId: string,
  jobId: string,
  name: string,
): string => {
  const safeName = name
    .split('/')
    .filter((part) => part !== '' && part !== '.' && part !== '..')
    .map(encodeURIComponent)
    .join('/');
  return (
    `${env.apiBaseUrl}/api/v1/projects/${encodeURIComponent(projectId)}` +
    `/revisions/${encodeURIComponent(revisionId)}/cad/${encodeURIComponent(jobId)}` +
    `/artifacts/${safeName}`
  );
};

/** Короткая форма SHA-256 для подписи; полный хеш — в title. */
export const shortSha = (sha: string): string => sha.slice(0, 12);
