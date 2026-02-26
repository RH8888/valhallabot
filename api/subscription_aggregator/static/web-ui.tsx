type PageMode = 'login' | 'users';

type UserRecord = {
  username: string;
  plan_limit_bytes: number;
  used_bytes: number;
  expire_at?: string | null;
  service_id?: number | null;
  disabled: boolean;
};

type UsersResponse = {
  total: number;
  total_used_bytes?: number;
  users: UserRecord[];
};

type ServiceRecord = {
  id: number;
  name: string;
};

type SubscriptionResponse = {
  urls: string[];
  qr_data_uris: string[];
};

const { useEffect, useMemo, useState } = React;
const numberFormatter = new Intl.NumberFormat();
const THEME_KEY = 'vb-theme';

function useTheme() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const stored = window.localStorage.getItem(THEME_KEY);
    return stored === 'light' ? 'light' : 'dark';
  });

  useEffect(() => {
    document.body.dataset.theme = theme;
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  return {
    theme,
    toggleTheme: () => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark')),
  };
}

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
  const { theme, toggleTheme } = useTheme();
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
        <div className="vb-inline-head">
          <p className="vb-chip">Valhalla Web Console</p>
          <button type="button" className="vb-secondary-btn" onClick={toggleTheme}>
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
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
  const { theme, toggleTheme } = useTheme();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [totalUsageBytes, setTotalUsageBytes] = useState(0);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [services, setServices] = useState<ServiceRecord[]>([]);
  const [busyUser, setBusyUser] = useState<string>('');
  const [selectedUser, setSelectedUser] = useState<UserRecord | null>(null);
  const [formLimit, setFormLimit] = useState('');
  const [formRenewDays, setFormRenewDays] = useState('');
  const [formServiceId, setFormServiceId] = useState('');
  const [subInfo, setSubInfo] = useState<SubscriptionResponse | null>(null);
  const [createUsername, setCreateUsername] = useState('');
  const [createLimitGb, setCreateLimitGb] = useState('');
  const [createDurationDays, setCreateDurationDays] = useState('');
  const [createServiceId, setCreateServiceId] = useState('');
  const [creatingUser, setCreatingUser] = useState(false);
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const parsedLimitGb = Number(formLimit);
  const canSetLimit = Number.isFinite(parsedLimitGb) && parsedLimitGb >= 0;

  const reloadUsers = async () => {
    const usersRes = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
    if (usersRes.status === 401) {
      window.location.replace('/web/login');
      return;
    }
    if (!usersRes.ok) {
      throw new Error('load users failed');
    }
    const data = (await usersRes.json()) as UsersResponse;
    setUsers(data.users || []);
    setTotalUsageBytes(data.total_used_bytes || 0);
  };

  useEffect(() => {
    const boot = async () => {
      try {
        const meRes = await fetch('/api/v1/web/me', { credentials: 'same-origin' });
        if (!meRes.ok) {
          window.location.replace('/web/login');
          return;
        }

        const [usersRes, servicesRes] = await Promise.all([
          fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' }),
          fetch('/api/v1/web/services', { credentials: 'same-origin' }),
        ]);
        if (usersRes.status === 401) {
          window.location.replace('/web/login');
          return;
        }
        if (!usersRes.ok) {
          throw new Error('load failed');
        }
        const data = (await usersRes.json()) as UsersResponse;
        const serviceData = servicesRes.ok ? ((await servicesRes.json()) as ServiceRecord[]) : [];
        setUsers(Array.isArray(data.users) ? data.users : []);
        setTotalUsageBytes(Number(data.total_used_bytes || 0));
        setServices(Array.isArray(serviceData) ? serviceData : []);
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

  const createUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!createUsername.trim()) {
      setError('Username is required.');
      return;
    }

    const limitGbNumber = Number(createLimitGb || '0');
    const durationDaysNumber = Number(createDurationDays || '0');
    if (!Number.isFinite(limitGbNumber) || limitGbNumber < 0) {
      setError('Traffic limit must be a non-negative number.');
      return;
    }
    if (!Number.isFinite(durationDaysNumber) || durationDaysNumber < 0) {
      setError('Duration days must be a non-negative number.');
      return;
    }

    setCreatingUser(true);
    try {
      const res = await fetch('/api/v1/web/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          username: createUsername.trim(),
          limit_bytes: Math.round(limitGbNumber * 1024 * 1024 * 1024),
          duration_days: Math.round(durationDaysNumber),
          service_id: createServiceId ? Number(createServiceId) : null,
        }),
      });
      if (res.status === 401) {
        window.location.replace('/web/login');
        return;
      }
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(payload.detail || 'Could not create user.');
        return;
      }
      setCreateUsername('');
      setCreateLimitGb('');
      setCreateDurationDays('');
      setCreateServiceId('');
      setShowCreateUserModal(false);
      await reloadUsers();
    } catch {
      setError('Could not create user. Please try again.');
    } finally {
      setCreatingUser(false);
    }
  };

  const openManage = (user: UserRecord) => {
    setSelectedUser(user);
    setFormLimit('');
    setFormRenewDays('');
    setFormServiceId(user.service_id ? String(user.service_id) : '');
    setSubInfo(null);
    setError('');
  };

  const closeManage = () => {
    setSelectedUser(null);
    setSubInfo(null);
    setBusyUser('');
  };

  const applyAction = async (payload: Record<string, unknown>) => {
    if (!selectedUser) return;
    setBusyUser(selectedUser.username);
    setError('');
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('update failed');
      const updated = (await res.json()) as UserRecord;
      setUsers((prev) => prev.map((u) => (u.username === updated.username ? updated : u)));
      setSelectedUser(updated);
    } catch {
      setError('Could not update user. Please try again.');
    } finally {
      setBusyUser('');
    }
  };

  const loadQr = async () => {
    if (!selectedUser) return;
    setBusyUser(selectedUser.username);
    setError('');
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}/subscription`, {
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('qr failed');
      setSubInfo((await res.json()) as SubscriptionResponse);
    } catch {
      setError('Could not load QR code for this user.');
    } finally {
      setBusyUser('');
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
          <div className="vb-header-actions">
            <button type="button" onClick={toggleTheme} className="vb-secondary-btn">
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <button type="button" onClick={logout} className="vb-secondary-btn">Logout</button>
          </div>
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
          <button type="button" onClick={() => setShowCreateUserModal(true)}>Add user</button>
        </div>

        {error ? <p className="vb-error">{error}</p> : null}

        <div className="vb-table-wrap">
          <table>
            <thead>
              <tr><th>Username</th><th>Plan limit</th><th>Used</th><th>Expires at</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6}>Loading users…</td></tr>
              ) : filteredUsers.length === 0 ? (
                <tr><td colSpan={6}>No users found.</td></tr>
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
                    <td><button type="button" className="vb-secondary-btn" onClick={() => openManage(user)}>Manage</button></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {showCreateUserModal ? (
          <div className="vb-modal-overlay" role="presentation" onClick={() => setShowCreateUserModal(false)}>
            <section className="vb-manage-panel" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
              <div className="vb-modal-head">
                <h3>Add user</h3>
                <button type="button" className="vb-secondary-btn" onClick={() => setShowCreateUserModal(false)}>Close</button>
              </div>
              <form className="vb-create-user" onSubmit={createUser}>
                <input
                  value={createUsername}
                  onChange={(event) => setCreateUsername(event.target.value)}
                  placeholder="Username"
                  aria-label="Create username"
                  required
                />
                <input
                  value={createLimitGb}
                  onChange={(event) => setCreateLimitGb(event.target.value)}
                  placeholder="Limit (GB)"
                  aria-label="Create traffic limit in GB"
                />
                <input
                  value={createDurationDays}
                  onChange={(event) => setCreateDurationDays(event.target.value)}
                  placeholder="Duration (days)"
                  aria-label="Create duration days"
                />
                <select
                  value={createServiceId}
                  onChange={(event) => setCreateServiceId(event.target.value)}
                  aria-label="Create service"
                >
                  <option value="">No service</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                </select>
                <button type="submit" disabled={creatingUser}>{creatingUser ? 'Creating…' : 'Create user'}</button>
              </form>
            </section>
          </div>
        ) : null}

        {selectedUser ? (
          <div className="vb-modal-overlay" role="presentation" onClick={closeManage}>
            <section className="vb-manage-panel" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="vb-modal-head">
            <h3>Manage @{selectedUser.username}</h3>
            <button type="button" className="vb-secondary-btn" onClick={closeManage}>Close</button>
            </div>
            <div className="vb-manage-grid">
              <label>
                New traffic limit (GB)
                <input value={formLimit} onChange={(e) => setFormLimit(e.target.value)} placeholder="e.g. 10" />
                <button type="button" disabled={busyUser === selectedUser.username || !formLimit.trim() || !canSetLimit} onClick={() => applyAction({ limit_bytes: Math.round(parsedLimitGb * 1024 * 1024 * 1024) })}>Set limit</button>
              </label>
              <label>
                Renew days
                <input value={formRenewDays} onChange={(e) => setFormRenewDays(e.target.value)} placeholder="e.g. 30" />
                <button type="button" disabled={busyUser === selectedUser.username || !formRenewDays.trim()} onClick={() => applyAction({ renew_days: Number(formRenewDays) })}>Renew</button>
              </label>
              <label>
                Assign service
                <select value={formServiceId} onChange={(e) => setFormServiceId(e.target.value)}>
                  <option value="">Select service</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                </select>
                <button type="button" disabled={busyUser === selectedUser.username || !formServiceId} onClick={() => applyAction({ service_id: Number(formServiceId) })}>Assign service</button>
              </label>
              <label>
                Reset usage
                <p className="vb-hint">Sets used traffic to zero for this user.</p>
                <button type="button" disabled={busyUser === selectedUser.username} onClick={() => applyAction({ reset_used: true })}>Reset usage</button>
              </label>
            </div>
            <div className="vb-qr-wrap">
              <button type="button" disabled={busyUser === selectedUser.username} onClick={loadQr}>Show QR code</button>
              {subInfo ? (
                <div className="vb-qr-list">
                  {subInfo.urls.map((url, index) => (
                    <div key={url}>
                      <p className="vb-hint">{url}</p>
                      <img src={subInfo.qr_data_uris[index]} alt={`Subscription QR ${index + 1} for ${selectedUser.username}`} className="vb-qr-img" />
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </section>
          </div>
        ) : null}
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
