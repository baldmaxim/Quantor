import { redirect } from 'next/navigation';

const IndexPage = () => {
  redirect('/dashboard');
};

export default IndexPage;
