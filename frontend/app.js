const { BrowserRouter, Routes, Route, Link } = ReactRouterDOM;

function Login() {
  return React.createElement('div', null, 'Login Page');
}

function Dashboard() {
  return React.createElement('div', null, 'Dashboard');
}

function Subscriptions() {
  return React.createElement('div', null, 'Subscriptions');
}

function App() {
  return React.createElement(
    BrowserRouter,
    null,
    React.createElement('nav', null,
      React.createElement(Link, {to: '/login'}, 'Login'), ' | ',
      React.createElement(Link, {to: '/dashboard'}, 'Dashboard'), ' | ',
      React.createElement(Link, {to: '/subscriptions'}, 'Subscriptions')
    ),
    React.createElement(Routes, null,
      React.createElement(Route, {path: '/login', element: React.createElement(Login)}),
      React.createElement(Route, {path: '/dashboard', element: React.createElement(Dashboard)}),
      React.createElement(Route, {path: '/subscriptions', element: React.createElement(Subscriptions)}),
      React.createElement(Route, {path: '*', element: React.createElement(Login)})
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
