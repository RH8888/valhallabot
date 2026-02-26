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
    document.documentElement.dataset.theme = theme;
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
    <main className="valhalla-bg min-h-screen p-4">
      <section className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-md items-center justify-center">
        <article className="card w-full border border-base-300 bg-base-100/90 shadow-2xl backdrop-blur">
          <div className="card-body">
            <div className="flex items-center justify-between gap-2">
              <div className="badge badge-primary badge-outline">Valhalla Web Console</div>
              <button type="button" className="btn btn-sm btn-ghost" onClick={toggleTheme}>
                {theme === 'dark' ? 'Light mode' : 'Dark mode'}
              </button>
            </div>
            <h1 className="card-title text-3xl">Welcome back</h1>
            <p className="text-base-content/70">Sign in to securely manage users, quotas, and expiration dates.</p>
            <form onSubmit={submit} className="space-y-4">
              <label className="form-control w-full">
                <div className="label"><span className="label-text">Username</span></div>
                <input className="input input-bordered" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required placeholder="Enter your username" />
              </label>
              <label className="form-control w-full">
                <div className="label"><span className="label-text">Password</span></div>
                <input className="input input-bordered" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" type="password" required placeholder="Enter your password" />
              </label>
              <button className="btn btn-primary w-full" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
              {error ? <p className="text-sm text-error">{error}</p> : <p className="text-sm text-base-content/70">Session is protected with secure HTTP-only cookies.</p>}
            </form>
          </div>
        </article>
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
    <main className="valhalla-bg min-h-screen p-4 md:p-8">
      <section className="mx-auto max-w-7xl space-y-4">
        <div className="navbar rounded-2xl border border-base-300 bg-base-100/90 px-4 shadow-xl backdrop-blur">
          <div className="flex-1">
            <div>
              <div className="badge badge-primary badge-outline">Valhalla Dashboard</div>
              <h1 className="mt-2 text-2xl font-bold">Users</h1>
            </div>
          </div>
          <div className="flex-none gap-2">
            <button type="button" onClick={toggleTheme} className="btn btn-ghost btn-sm">{theme === 'dark' ? 'Light' : 'Dark'}</button>
            <button type="button" onClick={logout} className="btn btn-outline btn-sm">Logout</button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <div className="stat rounded-box border border-base-300 bg-base-100/90 shadow">
            <div className="stat-title">Total users</div><div className="stat-value text-primary">{numberFormatter.format(stats.totalUsers)}</div>
          </div>
          <div className="stat rounded-box border border-base-300 bg-base-100/90 shadow">
            <div className="stat-title">Disabled users</div><div className="stat-value text-warning">{numberFormatter.format(stats.disabled)}</div>
          </div>
          <div className="stat rounded-box border border-base-300 bg-base-100/90 shadow">
            <div className="stat-title">Total usage</div><div className="stat-value text-secondary text-2xl md:text-3xl">{formatBytes(stats.totalUsage)}</div>
          </div>
        </div>

        <div className="flex flex-col gap-3 rounded-2xl border border-base-300 bg-base-100/90 p-4 shadow lg:flex-row lg:items-center">
          <input className="input input-bordered w-full lg:max-w-sm" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by username" aria-label="Search by username" />
          <button type="button" className="btn btn-primary lg:ms-auto" onClick={() => setShowCreateUserModal(true)}>Add user</button>
        </div>

        {error ? <div className="alert alert-error"><span>{error}</span></div> : null}

        <div className="overflow-x-auto rounded-2xl border border-base-300 bg-base-100/90 shadow-xl">
          <table className="table table-zebra">
            <thead>
              <tr><th>Username</th><th>Plan limit</th><th>Used</th><th>Expires at</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="text-center">Loading users…</td></tr>
              ) : filteredUsers.length === 0 ? (
                <tr><td colSpan={6} className="text-center">No users found.</td></tr>
              ) : (
                filteredUsers.map((user) => (
                  <tr key={user.username}>
                    <td className="font-semibold">{user.username}</td>
                    <td>{formatBytes(user.plan_limit_bytes)}</td>
                    <td>{formatBytes(user.used_bytes)}</td>
                    <td>{parseDate(user.expire_at)}</td>
                    <td>
                      <span className={`badge ${user.disabled ? 'badge-error' : 'badge-success'} badge-outline`}>
                        {user.disabled ? 'Disabled' : 'Active'}
                      </span>
                    </td>
                    <td><button type="button" className="btn btn-sm" onClick={() => openManage(user)}>Manage</button></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {showCreateUserModal ? (
          <div className="modal modal-open">
            <div className="modal-box max-w-3xl">
              <h3 className="text-lg font-bold">Add user</h3>
              <form className="mt-3 grid gap-3 md:grid-cols-2" onSubmit={createUser}>
                <input className="input input-bordered md:col-span-2" value={createUsername} onChange={(event) => setCreateUsername(event.target.value)} placeholder="Username" aria-label="Create username" required />
                <input className="input input-bordered" value={createLimitGb} onChange={(event) => setCreateLimitGb(event.target.value)} placeholder="Limit (GB)" aria-label="Create traffic limit in GB" />
                <input className="input input-bordered" value={createDurationDays} onChange={(event) => setCreateDurationDays(event.target.value)} placeholder="Duration (days)" aria-label="Create duration days" />
                <select className="select select-bordered md:col-span-2" value={createServiceId} onChange={(event) => setCreateServiceId(event.target.value)} aria-label="Create service">
                  <option value="">No service</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                </select>
                <div className="modal-action md:col-span-2">
                  <button type="button" className="btn" onClick={() => setShowCreateUserModal(false)}>Close</button>
                  <button type="submit" className="btn btn-primary" disabled={creatingUser}>{creatingUser ? 'Creating…' : 'Create user'}</button>
                </div>
              </form>
            </div>
            <form method="dialog" className="modal-backdrop">
              <button type="button" onClick={() => setShowCreateUserModal(false)}>close</button>
            </form>
          </div>
        ) : null}

        {selectedUser ? (
          <div className="modal modal-open">
            <div className="modal-box max-w-5xl">
              <h3 className="text-lg font-bold">Manage @{selectedUser.username}</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="space-y-2 rounded-xl border border-base-300 p-4">
                  <p className="font-semibold">New traffic limit (GB)</p>
                  <input className="input input-bordered w-full" value={formLimit} onChange={(e) => setFormLimit(e.target.value)} placeholder="e.g. 10" />
                  <button className="btn btn-primary btn-sm" type="button" disabled={busyUser === selectedUser.username || !formLimit.trim() || !canSetLimit} onClick={() => applyAction({ limit_bytes: Math.round(parsedLimitGb * 1024 * 1024 * 1024) })}>Set limit</button>
                </div>
                <div className="space-y-2 rounded-xl border border-base-300 p-4">
                  <p className="font-semibold">Renew days</p>
                  <input className="input input-bordered w-full" value={formRenewDays} onChange={(e) => setFormRenewDays(e.target.value)} placeholder="e.g. 30" />
                  <button className="btn btn-primary btn-sm" type="button" disabled={busyUser === selectedUser.username || !formRenewDays.trim()} onClick={() => applyAction({ renew_days: Number(formRenewDays) })}>Renew</button>
                </div>
                <div className="space-y-2 rounded-xl border border-base-300 p-4">
                  <p className="font-semibold">Assign service</p>
                  <select className="select select-bordered w-full" value={formServiceId} onChange={(e) => setFormServiceId(e.target.value)}>
                    <option value="">Select service</option>
                    {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                  </select>
                  <button className="btn btn-primary btn-sm" type="button" disabled={busyUser === selectedUser.username || !formServiceId} onClick={() => applyAction({ service_id: Number(formServiceId) })}>Assign service</button>
                </div>
                <div className="space-y-2 rounded-xl border border-base-300 p-4">
                  <p className="font-semibold">Reset usage</p>
                  <p className="text-sm text-base-content/70">Sets used traffic to zero for this user.</p>
                  <button className="btn btn-warning btn-sm" type="button" disabled={busyUser === selectedUser.username} onClick={() => applyAction({ reset_used: true })}>Reset usage</button>
                </div>
              </div>
              <div className="mt-6 rounded-xl border border-base-300 p-4">
                <button className="btn btn-secondary btn-sm" type="button" disabled={busyUser === selectedUser.username} onClick={loadQr}>Show QR code</button>
                {subInfo ? (
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {subInfo.urls.map((url, index) => (
                      <div key={url} className="space-y-2 rounded-xl border border-base-300 p-3">
                        <p className="break-all text-xs text-base-content/70">{url}</p>
                        <img src={subInfo.qr_data_uris[index]} alt={`Subscription QR ${index + 1} for ${selectedUser.username}`} className="mx-auto w-44 rounded-lg bg-white p-2" />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="modal-action">
                <button type="button" className="btn" onClick={closeManage}>Close</button>
              </div>
            </div>
            <form method="dialog" className="modal-backdrop">
              <button type="button" onClick={closeManage}>close</button>
            </form>
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
