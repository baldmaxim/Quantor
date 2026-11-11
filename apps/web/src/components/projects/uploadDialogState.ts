import type { UploadItem } from '@/components/projects/UploadQueue';

/**
 * Состояние окна «Загрузить файлы»: что считается очередью и какая кнопка основная.
 *
 * Чистая функция, чтобы правила («всё загружено — «Загрузить» не нужна») проверялись тестом,
 * а не глазами.
 */

export interface IUploadDialogStateInput {
  /** Файлы в очереди выбранных: допустимые к загрузке. Успешно загруженные из неё уже убраны. */
  readonly pendingCount: number;
  readonly running: boolean;
  readonly items: readonly Pick<UploadItem, 'stage'>[];
}

export interface IUploadDialogState {
  /** Основная кнопка: «Загрузить» или «Готово» (закрыть окно). */
  readonly primary: 'upload' | 'done';
  /** Можно ли сейчас нажать «Загрузить». */
  readonly canUpload: boolean;
}

export const getUploadDialogState = ({
  pendingCount,
  running,
  items,
}: IUploadDialogStateInput): IUploadDialogState => {
  const hasDone = items.some((item) => item.stage === 'готово');
  const allDone = !running && pendingCount === 0 && hasDone;

  return {
    primary: allDone ? 'done' : 'upload',
    canUpload: !running && pendingCount > 0,
  };
};
