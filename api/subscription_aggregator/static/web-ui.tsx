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
    document.documentElement.classList.toggle('dark', theme === 'dark');
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

const cardClass = 'rounded-2xl border border-slate-200/80 bg-white/95 p-6 shadow-2xl shadow-slate-900/10 backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:shadow-black/30';
const inputClass = 'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-slate-900 focus:ring-2 focus:ring-slate-400/30 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-slate-200 dark:focus:ring-slate-500/30';
const secondaryButtonClass = 'rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700';
const primaryButtonClass = 'rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white';

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
    <main className="min-h-screen bg-gradient-to-br from-white via-slate-100 to-slate-200 p-4 dark:from-slate-950 dark:via-slate-900 dark:to-black">
      <section className="mx-auto mt-12 max-w-md">
        <div className={cardClass}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-800 dark:bg-slate-700 dark:text-slate-100">
              Valhalla Web Console
            </span>
            <button type="button" className={secondaryButtonClass} onClick={toggleTheme}>
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
          </div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-white">Welcome back</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">Sign in to securely manage users, quotas, and expiration dates.</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
              Username
              <input
                className={inputClass}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                required
                placeholder="Enter your username"
              />
            </label>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
              Password
              <input
                className={inputClass}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                type="password"
                required
                placeholder="Enter your password"
              />
            </label>
            <button type="submit" disabled={busy} className={`${primaryButtonClass} w-full`}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
            {error ? <p className="text-sm font-medium text-rose-500">{error}</p> : <p className="text-sm text-slate-500 dark:text-slate-300">Session is protected with secure HTTP-only cookies.</p>}
          </form>
        </div>
      </section>
    </main>
  );
}

function UsersPage() {
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
    <main className="min-h-screen bg-gradient-to-br from-white via-slate-100 to-slate-200 p-4 dark:from-slate-950 dark:via-slate-900 dark:to-black">
      <section className={`mx-auto max-w-6xl ${cardClass}`}>
        <div className="flex gap-4">
          <aside className={`fixed inset-y-0 left-0 z-40 w-64 border-r border-slate-200 bg-white/95 p-4 shadow-xl transition-transform duration-200 dark:border-slate-700 dark:bg-slate-900/95 md:static md:translate-x-0 md:rounded-xl md:shadow-none ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
            <div className="mb-5 flex items-center justify-between md:justify-start">
              <p className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-300">Navigation</p>
              <button type="button" className="md:hidden rounded-lg border border-slate-300 px-2 py-1 text-slate-700 dark:border-slate-600 dark:text-slate-100" onClick={() => setSidebarOpen(false)}>✕</button>
            </div>
            <nav className="space-y-2">
              <a href="#" className="block rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900">Users</a>
              <span className="block rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-500 dark:border-slate-600 dark:text-slate-300">Add future section</span>
            </nav>
          </aside>
          {sidebarOpen ? <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setSidebarOpen(false)} /> : null}

          <div className="w-full">
        <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <button type="button" onClick={() => setSidebarOpen((prev) => !prev)} className="mb-3 inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 md:hidden">
              <span className="space-y-1">
                <span className="block h-0.5 w-4 bg-current" />
                <span className="block h-0.5 w-4 bg-current" />
                <span className="block h-0.5 w-4 bg-current" />
              </span>
              Menu
            </button>
            <span className="rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-800 dark:bg-slate-700 dark:text-slate-100">Valhalla Dashboard</span>
            <h1 className="mt-3 text-3xl font-bold text-slate-900 dark:text-white">Users</h1>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Monitor quota usage and account status in one place.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={toggleTheme} className={secondaryButtonClass}>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</button>
            <button type="button" onClick={logout} className={secondaryButtonClass}>Logout</button>
          </div>
        </header>

        <section className="grid gap-3 md:grid-cols-3">
          <article className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-300">Total users</p>
            <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{numberFormatter.format(stats.totalUsers)}</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-300">Disabled users</p>
            <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{numberFormatter.format(stats.disabled)}</p>
          </article>
          <article className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-300">Total usage</p>
            <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{formatBytes(stats.totalUsage)}</p>
          </article>
        </section>

        <div className="mt-5 flex flex-col gap-3 sm:flex-row">
          <input
            className={inputClass}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by username"
            aria-label="Search by username"
          />
          <button type="button" className={primaryButtonClass} onClick={() => setShowCreateUserModal(true)}>Add user</button>
        </div>

        {error ? <p className="mt-3 text-sm font-medium text-rose-500">{error}</p> : null}

        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
          <table className="min-w-[760px] w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
              <tr>
                <th className="px-4 py-3 font-semibold">Username</th><th className="px-4 py-3 font-semibold">Plan limit</th><th className="px-4 py-3 font-semibold">Used</th><th className="px-4 py-3 font-semibold">Expires at</th><th className="px-4 py-3 font-semibold">Status</th><th className="px-4 py-3 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td className="px-4 py-6 text-slate-500 dark:text-slate-300" colSpan={6}>Loading users…</td></tr>
              ) : filteredUsers.length === 0 ? (
                <tr><td className="px-4 py-6 text-slate-500 dark:text-slate-300" colSpan={6}>No users found.</td></tr>
              ) : (
                filteredUsers.map((user) => (
                  <tr key={user.username} className="border-t border-slate-200 dark:border-slate-700">
                    <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-100">{user.username}</td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">{formatBytes(user.plan_limit_bytes)}</td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">{formatBytes(user.used_bytes)}</td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-200">{parseDate(user.expire_at)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${user.disabled ? 'border-rose-300 bg-rose-100 text-rose-700 dark:border-rose-800 dark:bg-rose-900/40 dark:text-rose-200' : 'border-emerald-300 bg-emerald-100 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'}`}>
                        {user.disabled ? 'Disabled' : 'Active'}
                      </span>
                    </td>
                    <td className="px-4 py-3"><button type="button" className={secondaryButtonClass} onClick={() => openManage(user)}>Manage</button></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {showCreateUserModal ? (
          <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4" role="presentation" onClick={() => setShowCreateUserModal(false)}>
            <section className={`w-full max-w-3xl ${cardClass}`} role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
              <div className="mb-4 flex items-center justify-between gap-2">
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">Add user</h3>
                <button type="button" className={secondaryButtonClass} onClick={() => setShowCreateUserModal(false)}>Close</button>
              </div>
              <form className="grid gap-3 md:grid-cols-2" onSubmit={createUser}>
                <input className={inputClass} value={createUsername} onChange={(event) => setCreateUsername(event.target.value)} placeholder="Username" aria-label="Create username" required />
                <input className={inputClass} value={createLimitGb} onChange={(event) => setCreateLimitGb(event.target.value)} placeholder="Limit (GB)" aria-label="Create traffic limit in GB" />
                <input className={inputClass} value={createDurationDays} onChange={(event) => setCreateDurationDays(event.target.value)} placeholder="Duration (days)" aria-label="Create duration days" />
                <select className={inputClass} value={createServiceId} onChange={(event) => setCreateServiceId(event.target.value)} aria-label="Create service">
                  <option value="">No service</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                </select>
                <button type="submit" disabled={creatingUser} className={`${primaryButtonClass} md:col-span-2`}>{creatingUser ? 'Creating…' : 'Create user'}</button>
              </form>
            </section>
          </div>
        ) : null}

        {selectedUser ? (
          <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 p-4" role="presentation" onClick={closeManage}>
            <section className={`w-full max-w-4xl ${cardClass}`} role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
              <div className="mb-4 flex items-center justify-between gap-2">
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">Manage @{selectedUser.username}</h3>
                <button type="button" className={secondaryButtonClass} onClick={closeManage}>Close</button>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  New traffic limit (GB)
                  <input className={inputClass} value={formLimit} onChange={(e) => setFormLimit(e.target.value)} placeholder="e.g. 10" />
                  <button type="button" className={primaryButtonClass} disabled={busyUser === selectedUser.username || !formLimit.trim() || !canSetLimit} onClick={() => applyAction({ limit_bytes: Math.round(parsedLimitGb * 1024 * 1024 * 1024) })}>Set limit</button>
                </label>
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  Renew days
                  <input className={inputClass} value={formRenewDays} onChange={(e) => setFormRenewDays(e.target.value)} placeholder="e.g. 30" />
                  <button type="button" className={primaryButtonClass} disabled={busyUser === selectedUser.username || !formRenewDays.trim()} onClick={() => applyAction({ renew_days: Number(formRenewDays) })}>Renew</button>
                </label>
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  Assign service
                  <select className={inputClass} value={formServiceId} onChange={(e) => setFormServiceId(e.target.value)}>
                    <option value="">Select service</option>
                    {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                  </select>
                  <button type="button" className={primaryButtonClass} disabled={busyUser === selectedUser.username || !formServiceId} onClick={() => applyAction({ service_id: Number(formServiceId) })}>Assign service</button>
                </label>
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  Reset usage
                  <p className="text-xs text-slate-500 dark:text-slate-300">Sets used traffic to zero for this user.</p>
                  <button type="button" className={primaryButtonClass} disabled={busyUser === selectedUser.username} onClick={() => applyAction({ reset_used: true })}>Reset usage</button>
                </label>
              </div>
              <div className="mt-6 space-y-3">
                <button type="button" className={primaryButtonClass} disabled={busyUser === selectedUser.username} onClick={loadQr}>Show QR code</button>
                {subInfo ? (
                  <div className="grid gap-3 md:grid-cols-2">
                    {subInfo.urls.map((url, index) => (
                      <div key={url} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800">
                        <p className="mb-2 break-all text-xs text-slate-500 dark:text-slate-300">{url}</p>
                        <img src={subInfo.qr_data_uris[index]} alt={`Subscription QR ${index + 1} for ${selectedUser.username}`} className="h-44 w-44 rounded-lg bg-white p-2" />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </section>
          </div>
        ) : null}
          </div>
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
