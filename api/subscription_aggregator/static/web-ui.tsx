import { LoginPage } from '/static/pages/LoginPage.tsx';
import { UsersPage } from '/static/pages/UsersPage.tsx';

function App() {
  const page = document.body.dataset.page;
  if (page === 'users') return <UsersPage />;
  return <LoginPage />;
}

const rootNode = document.getElementById('root');
if (rootNode) {
  ReactDOM.createRoot(rootNode).render(<App />);
}
