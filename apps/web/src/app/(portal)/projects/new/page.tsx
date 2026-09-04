import { redirect } from 'next/navigation';

/**
 * Отдельный адрес создания проекта.
 *
 * Диалог живёт на списке проектов и открывается параметром адреса — так за ним виден
 * список, а ссылку по-прежнему можно сохранить и переслать.
 */
const NewProjectPage = () => {
  redirect('/projects?create=1');
};

export default NewProjectPage;
