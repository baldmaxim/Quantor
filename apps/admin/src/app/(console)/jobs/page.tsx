import { Planned } from '@/components/common/Planned';
import { Section } from '@/components/common/Section';

const Page = () => (
  <Section
    title={'Задания и воркеры'}
    description="Раздел объявлен, но ещё не реализован. Показано то, что появится, и когда."
  >
    <Planned
      title={'Задания и воркеры — пока пусто'}
      willShow={[
        'очередь, выполняющиеся и отказавшие задания',
        'число попыток и исполнитель',
        'безопасный текст ошибки — без содержимого документов',
        'повтор там, где он идемпотентен',
      ]}
      stage={'Промт 08 · вместе с выносом исполнения в отдельный процесс'}
    />
  </Section>
);

export default Page;
