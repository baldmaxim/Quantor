'use client';

import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';

import { Section } from '@/components/common/Section';
import { useCheckModelProvider, useModelProviders } from '@/lib/queries';

/**
 * Реестр поставщиков моделей.
 *
 * Только просмотр. Поставщики описываются развёртыванием: адрес модели и ключ к ней
 * относятся к устройству установки, а не к продуктовым настройкам. Кнопки «добавить»
 * здесь нет и не будет до появления шлюза моделей — заводить её ради нуля настроенных
 * поставщиков значило бы обещать управление, которого нет.
 *
 * Ключ доступа не показывается ни целиком, ни частями: сервер отдаёт только имя
 * переменной окружения и признак «задана». Маскировать нечего — значения просто нет.
 *
 * Связь проверяется по кнопке и щупает доступность адреса, а не выполняет запрос
 * к модели: на этом этапе портал к моделям не обращается вовсе.
 */

const POLICY_VIEW = {
  local_only: { label: 'только локально', tone: 'success' },
  remote_allowed: { label: 'разрешено наружу', tone: 'warning' },
  restricted_data: { label: 'ограниченные данные', tone: 'accent' },
} as const;

const Page = () => {
  const providers = useModelProviders();
  const probe = useCheckModelProvider();

  if (providers.isPending) return <SkeletonRows rows={4} />;
  if (providers.isError) {
    return (
      <ErrorState
        title="Реестр не загрузился"
        onRetry={() => void providers.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  return (
    <Section
      title="Провайдеры моделей"
      description="Что описано развёртыванием. Портал к моделям не обращается: на этом этапе реестр только описывает, что настроено."
    >
      {providers.data.length === 0 ? (
        <EmptyState
          title="Поставщики не описаны"
          description={
            <span className="flex flex-col gap-[var(--s-3)]">
              <span>
                Реестр задаётся переменной окружения <span className="mono">MODEL_PROVIDERS</span>:
                адрес модели и ключ к ней относятся к устройству установки, а не к настройкам
                продукта.
              </span>
              <span className="text-micro">
                Ключи в реестре не хранятся — только имя переменной, в которой лежит ключ.
              </span>
            </span>
          }
        />
      ) : (
        <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Поставщик</th>
                <th>Данные</th>
                <th>Ключ</th>
                <th>Модели</th>
                <th>Готовность</th>
                <th>Связь</th>
              </tr>
            </thead>
            <tbody>
              {providers.data.map((provider) => {
                const policy = POLICY_VIEW[provider.policy];
                const result = probe.data?.provider_id === provider.id ? probe.data : null;

                return (
                  <tr key={provider.id}>
                    <td>
                      <div className="flex flex-col gap-[2px]">
                        <span className="font-medium">{provider.name}</span>
                        <span className="text-micro text-muted">{provider.kind}</span>
                        <span className="mono text-micro text-muted wrap-anywhere">
                          {provider.endpoint_label}
                        </span>
                      </div>
                    </td>
                    <td>
                      <StatusBadge tone={policy.tone}>{policy.label}</StatusBadge>
                    </td>
                    <td>
                      {provider.credential_env === null ? (
                        <span className="text-micro text-muted">не требуется</span>
                      ) : (
                        <div className="flex flex-col gap-[2px]">
                          <StatusBadge tone={provider.credential_configured ? 'success' : 'danger'}>
                            {provider.credential_configured ? 'задан' : 'отсутствует'}
                          </StatusBadge>
                          <span className="mono text-micro text-muted">
                            {provider.credential_env}
                          </span>
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="flex flex-col gap-[var(--s-2)]">
                        {provider.models.length === 0 ? (
                          <span className="text-micro text-muted">не перечислены</span>
                        ) : (
                          provider.models.map((model) => (
                            <div key={model.model_id} className="flex flex-col gap-[1px]">
                              <span className="mono text-micro">{model.model_id}</span>
                              <span className="text-micro text-muted">
                                {model.capabilities.join(', ')}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </td>
                    <td>
                      <StatusBadge tone={provider.is_usable ? 'success' : 'neutral'}>
                        {provider.is_usable ? 'готов' : provider.enabled ? 'нет ключа' : 'выключен'}
                      </StatusBadge>
                    </td>
                    <td>
                      <div className="flex flex-col gap-[var(--s-3)]">
                        <Button
                          compact
                          disabled={!provider.is_usable || probe.isPending}
                          title={
                            provider.is_usable ? undefined : 'Поставщик не готов: проверять нечего'
                          }
                          onClick={() => probe.mutate(provider.id)}
                        >
                          Проверить
                        </Button>
                        {result && (
                          <div className="flex flex-col gap-[2px]">
                            <StatusBadge tone={result.status === 'healthy' ? 'success' : 'danger'}>
                              {result.status === 'healthy' ? 'адрес отвечает' : 'нет связи'}
                            </StatusBadge>
                            <span className="text-micro text-muted">
                              {result.latency_ms} мс · {result.detail}
                            </span>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-dashed border-border-strong p-[var(--s-5)]">
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Чего здесь нет
        </h3>
        <p className="max-w-[70ch] text-sm text-muted">
          Вызовов моделей. Реестр описывает возможности и границы — куда позволено уходить данным,
          какие модели заявлены, задан ли ключ. Сам шлюз появится на Stage 2 вместе с первым, кто к
          моделям обратится.
        </p>
        <p className="text-micro text-muted">
          Ротация ключа: изменить значение переменной окружения и перезапустить процесс.
        </p>
      </div>
    </Section>
  );
};

export default Page;
