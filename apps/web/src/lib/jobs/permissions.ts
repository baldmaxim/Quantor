/** Права очереди заданий; значения совпадают с `Permission` в `apps/api/app/auth/permissions.py`. */
// Очередь читает `/admin/jobs`, а весь `/admin` закрыт правом `system.admin`.
export const QUEUE_ACCESS_PERMISSION = 'system.admin';
export const JOBS_MANAGE_PERMISSION = 'jobs.manage';
