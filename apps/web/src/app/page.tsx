import { redirect } from 'next/navigation';

/** Корень портала — это список проектов. */
const HomePage = () => {
  redirect('/projects');
};

export default HomePage;
