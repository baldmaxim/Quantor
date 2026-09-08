import { Planned } from '@/components/common/Planned';
import { Section } from '@/components/common/Section';

const Page = () => (
  <Section
    title={'Провайдеры моделей'}
    description="Раздел объявлен, но ещё не реализован. Показано то, что появится, и когда."
  >
    <Planned
      title={'Провайдеры моделей — пока пусто'}
      willShow={[
        'реестр провайдеров: тип, эндпоинт, включён ли',
        'модели и их возможности',
        'классификация «локально / удалённо / ограниченные данные»',
        'состояние последней явной проверки связи',
      ]}
      stage={'Промт 07 · вызовов моделей не будет и тогда'}
    />
  </Section>
);

export default Page;
