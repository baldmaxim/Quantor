import { Planned } from '@/components/common/Planned';
import { Section } from '@/components/common/Section';

const Page = () => (
  <Section
    title={'Рабочие пространства'}
    description="Раздел объявлен, но ещё не реализован. Показано то, что появится, и когда."
  >
    <Planned
      title={'Рабочие пространства — пока пусто'}
      willShow={[
        'список арендаторов и их состояние',
        'участники пространства и их роли',
        'создание и приостановка пространства',
      ]}
      stage={'Появится вместе с административным API управления доступом'}
    />
  </Section>
);

export default Page;
