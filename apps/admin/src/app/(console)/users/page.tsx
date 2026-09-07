import { Planned } from '@/components/common/Planned';
import { Section } from '@/components/common/Section';

const Page = () => (
  <Section
    title={'Пользователи и доступ'}
    description="Раздел объявлен, но ещё не реализован. Показано то, что появится, и когда."
  >
    <Planned
      title={'Пользователи и доступ — пока пусто'}
      willShow={[
        'личности, пришедшие от провайдера входа',
        'членство в пространствах и роли',
        'матрица разрешений — только для чтения, она задана кодом',
        'отзыв активных сеансов',
      ]}
      stage={'Появится вместе с административным API управления доступом'}
    />
  </Section>
);

export default Page;
