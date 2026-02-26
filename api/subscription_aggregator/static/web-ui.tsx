/** @jsxImportSource https://esm.sh/react@18.3.1 */
import * as React from 'https://esm.sh/react@18.3.1';
import * as ReactDOM from 'https://esm.sh/react-dom@18.3.1/client';
import * as Dialog from 'https://esm.sh/@radix-ui/react-dialog@1.1.2?bundle';

type PageMode = 'login' | 'users';
type UserFormMode = 'create' | 'edit';

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

type LayoutShellProps = {
  title: string;
  subtitle: string;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onLogout: () => void;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
};

function LayoutShell(props: LayoutShellProps) {
  const { title, subtitle, theme, onToggleTheme, onLogout, headerAction, children } = props;
  return (
    <main className="vb-admin-shell">
      <aside className="vb-admin-sidebar">
        <h2>Valhalla Admin</h2>
        <nav>
          <a href="/web/users" className="vb-nav-link active" aria-current="page">Users</a>
        </nav>
      </aside>
      <section className="vb-main-content">
        <header className="vb-page-header">
          <div>
            <h1>{title}</h1>
            <p className="vb-subtitle">{subtitle}</p>
          </div>
          <div className="vb-page-actions">
            {headerAction}
            <button type="button" className="vb-secondary-btn" onClick={onToggleTheme}>
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <button type="button" className="vb-secondary-btn" onClick={onLogout}>Logout</button>
          </div>
        </header>
        <section className="vb-content-panel">{children}</section>
      </section>
    </main>
  );
}

type UsersTableProps = {
  users: UserRecord[];
  search: string;
  onSearchChange: (value: string) => void;
  loading: boolean;
  onEdit: (user: UserRecord) => void;
  onDelete: (user: UserRecord) => void;
};

function UsersTable(props: UsersTableProps) {
  const { users, search, onSearchChange, loading, onEdit, onDelete } = props;

  return (
    <>
      <div className="vb-table-toolbar">
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search by username"
          aria-label="Search users"
        />
      </div>
      <div className="vb-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Username</th>
              <th>Plan limit</th>
              <th>Used</th>
              <th>Expires at</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="vb-table-placeholder">Loading users…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="vb-table-placeholder">No users found for this search.</td></tr>
            ) : (
              users.map((user) => (
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
                  <td>
                    <div className="vb-row-actions">
                      <button type="button" className="vb-secondary-btn" onClick={() => onEdit(user)}>Edit</button>
                      <button type="button" className="vb-danger-btn" onClick={() => onDelete(user)}>
                        {user.disabled ? 'Enable' : 'Disable'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

type UserModalProps = {
  open: boolean;
  mode: UserFormMode;
  user: UserRecord | null;
  services: ServiceRecord[];
  onClose: () => void;
  onSubmit: (payload: {
    username: string;
    limitGb: number;
    durationDays: number;
    renewDays: number;
    serviceId: number | null;
  }) => Promise<void>;
};

function UserModal({ open, mode, user, services, onClose, onSubmit }: UserModalProps) {
  const [username, setUsername] = useState('');
  const [limitGb, setLimitGb] = useState('0');
  const [durationDays, setDurationDays] = useState('0');
  const [renewDays, setRenewDays] = useState('0');
  const [serviceId, setServiceId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setError('');
    if (mode === 'edit' && user) {
      setUsername(user.username);
      setLimitGb('0');
      setDurationDays('0');
      setRenewDays('0');
      setServiceId(user.service_id ? String(user.service_id) : '');
      return;
    }
    setUsername('');
    setLimitGb('0');
    setDurationDays('30');
    setRenewDays('0');
    setServiceId('');
  }, [mode, open, user]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');

    if (!username.trim()) {
      setError('Username is required.');
      return;
    }

    const parsedLimit = Number(limitGb || '0');
    const parsedDuration = Number(durationDays || '0');
    const parsedRenew = Number(renewDays || '0');

    if (!Number.isFinite(parsedLimit) || parsedLimit < 0) {
      setError('Traffic limit must be a non-negative number.');
      return;
    }
    if (!Number.isFinite(parsedDuration) || parsedDuration < 0) {
      setError('Duration days must be a non-negative number.');
      return;
    }
    if (!Number.isFinite(parsedRenew) || parsedRenew < 0) {
      setError('Renew days must be a non-negative number.');
      return;
    }

    setBusy(true);
    try {
      await onSubmit({
        username: username.trim(),
        limitGb: parsedLimit,
        durationDays: parsedDuration,
        renewDays: parsedRenew,
        serviceId: serviceId ? Number(serviceId) : null,
      });
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not save user.';
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  const isEdit = mode === 'edit';

  return (
    <Dialog.Root open={open} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="vb-modal-overlay" />
        <Dialog.Content className="vb-modal-content">
          <div className="vb-modal-head">
            <Dialog.Title>{isEdit ? `Edit ${user?.username || ''}` : 'Add user'}</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="vb-secondary-btn" aria-label="Close dialog">✕</button>
            </Dialog.Close>
          </div>

          {error ? <p className="vb-error">{error}</p> : null}

          <form className="vb-form" onSubmit={submit}>
            <label>
              Username
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                disabled={isEdit}
                autoFocus
              />
            </label>
            <label>
              Traffic limit (GB)
              <input
                type="number"
                min="0"
                value={limitGb}
                onChange={(event) => setLimitGb(event.target.value)}
                required
              />
            </label>
            {!isEdit ? (
              <label>
                Duration (days)
                <input
                  type="number"
                  min="0"
                  value={durationDays}
                  onChange={(event) => setDurationDays(event.target.value)}
                  required
                />
              </label>
            ) : (
              <label>
                Renew by (days)
                <input
                  type="number"
                  min="0"
                  value={renewDays}
                  onChange={(event) => setRenewDays(event.target.value)}
                />
              </label>
            )}
            <label>
              Service
              <select value={serviceId} onChange={(event) => setServiceId(event.target.value)}>
                <option value="">No service</option>
                {services.map((service) => (
                  <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>
                ))}
              </select>
            </label>

            <div className="vb-modal-footer">
              <button type="button" className="vb-secondary-btn" onClick={onClose} disabled={busy}>Cancel</button>
              <button type="submit" disabled={busy}>{busy ? 'Saving…' : isEdit ? 'Save changes' : 'Create user'}</button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
};

function ConfirmDialog({ open, title, description, confirmLabel, busy, onCancel, onConfirm }: ConfirmDialogProps) {
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) setError('');
  }, [open]);

  const confirm = async () => {
    setError('');
    try {
      await onConfirm();
      onCancel();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.');
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => (!next ? onCancel() : undefined)}>
      <Dialog.Portal>
        <Dialog.Overlay className="vb-modal-overlay" />
        <Dialog.Content className="vb-modal-content vb-confirm-dialog">
          <div className="vb-modal-head">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className="vb-secondary-btn" aria-label="Close dialog">✕</button>
            </Dialog.Close>
          </div>
          <p className="vb-subtitle">{description}</p>
          {error ? <p className="vb-error">{error}</p> : null}
          <div className="vb-modal-footer">
            <button type="button" className="vb-secondary-btn" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="button" className="vb-danger-btn" onClick={() => void confirm()} disabled={busy}>
              {busy ? 'Saving…' : confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/v1/web/me', { credentials: 'same-origin' })
      .then((res) => {
        if (res.ok) window.location.replace('/web/users');
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
      setError(res.status === 429 ? 'Too many login attempts. Try again later.' : 'Invalid username or password.');
    } catch {
      setError('Unable to login right now. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="vb-shell">
      <section className="vb-login-card">
        <h1>Welcome back</h1>
        <p className="vb-subtitle">Sign in to manage your users.</p>
        <form onSubmit={submit} className="vb-form">
          <label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
          {error ? <p className="vb-error">{error}</p> : null}
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
  const [selectedUser, setSelectedUser] = useState<UserRecord | null>(null);
  const [modalMode, setModalMode] = useState<UserFormMode>('create');
  const [showUserModal, setShowUserModal] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingDeleteUser, setPendingDeleteUser] = useState<UserRecord | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);

  const reloadUsers = async () => {
    const usersRes = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
    if (usersRes.status === 401) {
      window.location.replace('/web/login');
      return;
    }
    if (!usersRes.ok) throw new Error('Unable to load users.');
    const data = (await usersRes.json()) as UsersResponse;
    setUsers(Array.isArray(data.users) ? data.users : []);
    setTotalUsageBytes(Number(data.total_used_bytes || 0));
  };

  useEffect(() => {
    const boot = async () => {
      try {
        const meRes = await fetch('/api/v1/web/me', { credentials: 'same-origin' });
        if (!meRes.ok) {
          window.location.replace('/web/login');
          return;
        }
        const servicesRes = await fetch('/api/v1/web/services', { credentials: 'same-origin' });
        const serviceData = servicesRes.ok ? ((await servicesRes.json()) as ServiceRecord[]) : [];
        setServices(Array.isArray(serviceData) ? serviceData : []);
        await reloadUsers();
      } catch {
        setError('Unable to load users right now.');
      } finally {
        setLoading(false);
      }
    };

    void boot();
  }, []);

  const filteredUsers = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    const result = users.filter((user) => user.username.toLowerCase().includes(normalized));
    return result.sort((a, b) => a.username.localeCompare(b.username));
  }, [search, users]);

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

  const submitUser = async (payload: {
    username: string;
    limitGb: number;
    durationDays: number;
    renewDays: number;
    serviceId: number | null;
  }) => {
    setError('');
    if (modalMode === 'create') {
      const createRes = await fetch('/api/v1/web/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          username: payload.username,
          limit_bytes: Math.round(payload.limitGb * 1024 * 1024 * 1024),
          duration_days: Math.round(payload.durationDays),
          service_id: payload.serviceId,
        }),
      });
      if (!createRes.ok) {
        const detail = await createRes.json().catch(() => ({}));
        throw new Error(detail.detail || 'Could not create user.');
      }
      await reloadUsers();
      return;
    }

    if (!selectedUser) throw new Error('No user selected.');
    const editRes = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        limit_bytes: Math.round(payload.limitGb * 1024 * 1024 * 1024),
        renew_days: Math.round(payload.renewDays),
        service_id: payload.serviceId,
      }),
    });

    if (!editRes.ok) {
      const detail = await editRes.json().catch(() => ({}));
      throw new Error(detail.detail || 'Could not update user.');
    }
    await reloadUsers();
  };

  const requestToggleUser = (user: UserRecord) => {
    setPendingDeleteUser(user);
    setShowConfirm(true);
  };

  const confirmToggleUser = async () => {
    if (!pendingDeleteUser) return;
    setBusyDelete(true);
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(pendingDeleteUser.username)}?disable=${!pendingDeleteUser.disabled}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || 'Could not update user status.');
      }
      await reloadUsers();
    } finally {
      setBusyDelete(false);
    }
  };

  return (
    <LayoutShell
      title="Users"
      subtitle="Manage users from a dedicated admin panel with fast search and status controls."
      theme={theme}
      onToggleTheme={toggleTheme}
      onLogout={logout}
      headerAction={<button type="button" onClick={() => { setModalMode('create'); setSelectedUser(null); setShowUserModal(true); }}>Add user</button>}
    >
      <section className="vb-stat-grid">
        <article><span>Total users</span><strong>{numberFormatter.format(stats.totalUsers)}</strong></article>
        <article><span>Disabled users</span><strong>{numberFormatter.format(stats.disabled)}</strong></article>
        <article><span>Total usage</span><strong>{formatBytes(stats.totalUsage)}</strong></article>
      </section>

      {error ? <p className="vb-error">{error}</p> : null}

      <UsersTable
        users={filteredUsers}
        search={search}
        onSearchChange={setSearch}
        loading={loading}
        onEdit={(user) => {
          setModalMode('edit');
          setSelectedUser(user);
          setShowUserModal(true);
        }}
        onDelete={requestToggleUser}
      />

      <UserModal
        open={showUserModal}
        mode={modalMode}
        user={selectedUser}
        services={services}
        onClose={() => setShowUserModal(false)}
        onSubmit={submitUser}
      />

      <ConfirmDialog
        open={showConfirm}
        title={pendingDeleteUser?.disabled ? 'Enable user' : 'Disable user'}
        description={pendingDeleteUser ? `Are you sure you want to ${pendingDeleteUser.disabled ? 'enable' : 'disable'} @${pendingDeleteUser.username}?` : ''}
        confirmLabel={pendingDeleteUser?.disabled ? 'Enable user' : 'Disable user'}
        busy={busyDelete}
        onCancel={() => { setShowConfirm(false); setPendingDeleteUser(null); }}
        onConfirm={confirmToggleUser}
      />
    </LayoutShell>
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
