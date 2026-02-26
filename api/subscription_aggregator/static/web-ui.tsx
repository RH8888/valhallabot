type PageMode = 'login' | 'users';

type UserRecord = {
  username: string;
  plan_limit_bytes: number;
  used_bytes: number;
  expire_at?: string | null;
  disabled: boolean;
};

type UsersResponse = {
  total: number;
  total_used_bytes?: number;
  users: UserRecord[];
};

const { useEffect, useMemo, useState } = React;
const numberFormatter = new Intl.NumberFormat();

function formatBytes(value?: number | null): string {
  if (value === null || value === undefined) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let num = Number(value);
  let idx = 0;
  while (num >= 1024 && idx < units.length - 1) {
    num /= 1024;
    idx += 1;
  }
  return `${num.toFixed(idx === 0 ? 0 : 2)} ${units[idx]}`;
}

function parseDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/v1/web/me', { credentials: 'same-origin' })
      .then((res) => {
        if (res.ok) {
          window.location.replace('/web/users');
        }
      })
      .catch(() => undefined);
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      const res = await fetch('/api/v1/web/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ username, password }),
      });

      if (res.ok) {
        window.location.replace('/web/users');
        return;
      }
      if (res.status === 429) {
        setError('Too many login attempts. Please wait a bit and try again.');
        return;
      }
      setError('Invalid username or password.');
    } catch {
      setError('Unable to login right now. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="vb-shell">
      <section className="vb-login-card">
        <p className="vb-chip">Valhalla Web Console</p>
        <h1>Welcome back</h1>
        <p className="vb-subtitle">Sign in to securely manage users, quotas, and expiration dates.</p>
        <form onSubmit={submit} className="vb-form">
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
              placeholder="Enter your username"
            />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              type="password"
              required
              placeholder="Enter your password"
            />
          </label>
          <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          {error ? <p className="vb-error">{error}</p> : <p className="vb-hint">Session is protected with secure HTTP-only cookies.</p>}
        </form>
      </section>
    </main>
  );
}

function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [totalUsageBytes, setTotalUsageBytes] = useState(0);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const boot = async () => {
      try {
        const meRes = await fetch('/api/v1/web/me', { credentials: 'same-origin' });
        if (!meRes.ok) {
          window.location.replace('/web/login');
          return;
        }

        const usersRes = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
        if (usersRes.status === 401) {
          window.location.replace('/web/login');
          return;
        }
        if (!usersRes.ok) {
          throw new Error('load failed');
        }
        const data = (await usersRes.json()) as UsersResponse;
        setUsers(Array.isArray(data.users) ? data.users : []);
        setTotalUsageBytes(Number(data.total_used_bytes || 0));
      } catch {
        setError('Unable to load users right now.');
      } finally {
        setLoading(false);
      }
    };

    void boot();
  }, []);

  const filteredUsers = useMemo(
    () => users.filter((user) => user.username.toLowerCase().includes(search.trim().toLowerCase())),
    [search, users],
  );

  const stats = useMemo(() => {
    const disabled = users.filter((user) => user.disabled).length;
    return { totalUsers: users.length, disabled, totalUsage: totalUsageBytes };
  }, [users, totalUsageBytes]);

  const logout = async () => {
    try {
      await fetch('/api/v1/web/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.replace('/web/login');
    }
  };

  return (
    <main className="vb-shell vb-users-shell">
      <section className="vb-users-card">
        <header className="vb-users-header">
          <div>
            <p className="vb-chip">Valhalla Dashboard</p>
            <h1>Users</h1>
            <p className="vb-subtitle">Monitor quota usage and account status in one place.</p>
          </div>
          <button type="button" onClick={logout} className="vb-secondary-btn">Logout</button>
        </header>

        <section className="vb-stat-grid">
          <article><span>Total users</span><strong>{numberFormatter.format(stats.totalUsers)}</strong></article>
          <article><span>Disabled users</span><strong>{numberFormatter.format(stats.disabled)}</strong></article>
          <article><span>Total usage</span><strong>{formatBytes(stats.totalUsage)}</strong></article>
        </section>

        <div className="vb-table-toolbar">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by username"
            aria-label="Search by username"
          />
        </div>

        {error ? <p className="vb-error">{error}</p> : null}

        <div className="vb-table-wrap">
          <table>
            <thead>
              <tr><th>Username</th><th>Plan limit</th><th>Used</th><th>Expires at</th><th>Status</th></tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5}>Loading users…</td></tr>
              ) : filteredUsers.length === 0 ? (
                <tr><td colSpan={5}>No users found.</td></tr>
              ) : (
                filteredUsers.map((user) => (
                  <tr key={user.username}>
                    <td>{user.username}</td>
                    <td>{formatBytes(user.plan_limit_bytes)}</td>
                    <td>{formatBytes(user.used_bytes)}</td>
                    <td>{parseDate(user.expire_at)}</td>
                    <td>
                      <span className={user.disabled ? 'vb-badge danger' : 'vb-badge success'}>
                        {user.disabled ? 'Disabled' : 'Active'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function App() {
  const page = document.body.dataset.page as PageMode;
  if (page === 'users') return <UsersPage />;
  return <LoginPage />;
}

const rootNode = document.getElementById('root');
if (rootNode) {
  ReactDOM.createRoot(rootNode).render(<App />);
}
