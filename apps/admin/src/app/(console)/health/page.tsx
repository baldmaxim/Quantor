import { Planned } from '@/components/common/Planned';
import { Section } from '@/components/common/Section';

const Page = () => (
  <Section
    title={'Состояние системы'}
    description="Раздел объявлен, но ещё не реализован. Показано то, что появится, и когда."
  >
    <Planned
      title={'Состояние системы — пока пусто'}
      willShow={[
        'версии сборок портала и API',
        'PostgreSQL и головная ревизия миграций',
        'объектное хранилище',
        'пульс воркера, TenderHUB, провайдер входа',
      ]}
      stage={'Промт 10 · сейчас основное видно на обзоре'}
    />
  </Section>
);

export default Page;
