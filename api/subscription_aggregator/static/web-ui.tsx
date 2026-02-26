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

type UserFormValues = {
  username: string;
  limitGb: string;
  durationDays: string;
  renewDays: string;
  serviceId: string;
  resetUsed: boolean;
};

type SortDirection = 'asc' | 'desc';

declare global {
  interface Window {
    HeadlessUI?: {
      Dialog: React.ComponentType<any>;
      Transition: React.ComponentType<any> & { Child: React.ComponentType<any> };
    };
  }
}

const { useEffect, useMemo, useState, Fragment } = React;
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

function LayoutShell({
  title,
  onAddUser,
  onLogout,
  children,
}: {
  title: string;
  onAddUser: () => void;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto flex min-h-screen w-full max-w-[1400px] flex-col lg:flex-row">
        <aside className="w-full border-b border-slate-200 bg-white p-4 lg:w-72 lg:border-b-0 lg:border-r lg:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">Valhalla Admin</p>
          <nav className="mt-6 space-y-2">
            <a href="/web/users" className="block rounded-lg bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700">Users</a>
          </nav>
          <button
            type="button"
            onClick={onLogout}
            className="mt-6 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Logout
          </button>
        </aside>

        <main className="flex-1 p-4 md:p-6 lg:p-8">
          <header className="mb-6 flex flex-col gap-4 rounded-xl bg-white p-4 shadow-sm md:flex-row md:items-center md:justify-between md:p-6">
            <div>
              <h1 className="text-2xl font-semibold md:text-3xl">{title}</h1>
              <p className="mt-2 text-sm text-slate-500">Manage user accounts, quotas, and lifecycle actions from one place.</p>
            </div>
            <button
              type="button"
              onClick={onAddUser}
              className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
            >
              Add user
            </button>
          </header>
          {children}
        </main>
      </div>
    </div>
  );
}

function UsersTable({
  users,
  loading,
  search,
  sortDirection,
  onSearchChange,
  onToggleSort,
  onEdit,
  onDelete,
}: {
  users: UserRecord[];
  loading: boolean;
  search: string;
  sortDirection: SortDirection;
  onSearchChange: (value: string) => void;
  onToggleSort: () => void;
  onEdit: (user: UserRecord) => void;
  onDelete: (user: UserRecord) => void;
}) {
  return (
    <section className="rounded-xl bg-white p-4 shadow-sm md:p-6">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search users by username"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 md:max-w-sm"
          aria-label="Search users"
        />
        <button
          type="button"
          onClick={onToggleSort}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
        >
          Sort username ({sortDirection === 'asc' ? 'A → Z' : 'Z → A'})
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Username</th>
              <th className="px-4 py-3 font-medium">Plan limit</th>
              <th className="px-4 py-3 font-medium">Used</th>
              <th className="px-4 py-3 font-medium">Expires at</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Loading users…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">No users found.</td></tr>
            ) : (
              users.map((user) => (
                <tr key={user.username} className="border-t border-slate-200">
                  <td className="px-4 py-3 font-medium text-slate-900">{user.username}</td>
                  <td className="px-4 py-3 text-slate-600">{formatBytes(user.plan_limit_bytes)}</td>
                  <td className="px-4 py-3 text-slate-600">{formatBytes(user.used_bytes)}</td>
                  <td className="px-4 py-3 text-slate-600">{parseDate(user.expire_at)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${user.disabled ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                      {user.disabled ? 'Disabled' : 'Active'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button type="button" onClick={() => onEdit(user)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100">Edit</button>
                      <button type="button" onClick={() => onDelete(user)} className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50">Delete</button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UserModal({
  open,
  mode,
  services,
  values,
  saving,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mode: 'create' | 'edit';
  services: ServiceRecord[];
  values: UserFormValues;
  saving: boolean;
  error: string;
  onChange: (patch: Partial<UserFormValues>) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  if (!open) return null;

  const Dialog = window.HeadlessUI?.Dialog;
  const Transition = window.HeadlessUI?.Transition;
  const validUsername = values.username.trim().length >= 3;

  if (!Dialog || !Transition) {
    return null;
  }

  return (
    <Transition appear show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100" leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0">
          <div className="fixed inset-0 bg-slate-900/50" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto p-4">
          <div className="flex min-h-full items-center justify-center">
            <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100" leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95">
              <Dialog.Panel className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl">
                <div className="mb-6 flex items-start justify-between gap-4">
                  <div>
                    <Dialog.Title className="text-xl font-semibold text-slate-900">{mode === 'create' ? 'Add user' : `Edit ${values.username}`}</Dialog.Title>
                    <p className="mt-1 text-sm text-slate-500">{mode === 'create' ? 'Create a new user account with quota and duration settings.' : 'Update quota and service settings for this user.'}</p>
                  </div>
                  <button type="button" onClick={onClose} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100">Close</button>
                </div>

                <div className="space-y-4">
                  <label className="block text-sm font-medium text-slate-700">
                    Username
                    <input
                      disabled={mode === 'edit'}
                      value={values.username}
                      onChange={(event) => onChange({ username: event.target.value })}
                      className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 disabled:bg-slate-100"
                    />
                  </label>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="block text-sm font-medium text-slate-700">
                      Traffic limit (GB)
                      <input value={values.limitGb} onChange={(event) => onChange({ limitGb: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                    </label>
                    {mode === 'create' ? (
                      <label className="block text-sm font-medium text-slate-700">
                        Duration (days)
                        <input value={values.durationDays} onChange={(event) => onChange({ durationDays: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                      </label>
                    ) : (
                      <label className="block text-sm font-medium text-slate-700">
                        Renew days
                        <input value={values.renewDays} onChange={(event) => onChange({ renewDays: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                      </label>
                    )}
                  </div>

                  <label className="block text-sm font-medium text-slate-700">
                    Service
                    <select value={values.serviceId} onChange={(event) => onChange({ serviceId: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2">
                      <option value="">No service</option>
                      {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
                    </select>
                  </label>

                  {mode === 'edit' ? (
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input type="checkbox" checked={values.resetUsed} onChange={(event) => onChange({ resetUsed: event.target.checked })} />
                      Reset used traffic to zero
                    </label>
                  ) : null}
                </div>

                {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}

                <div className="mt-6 flex justify-end gap-3">
                  <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100">Cancel</button>
                  <button
                    type="button"
                    onClick={onSubmit}
                    disabled={saving || !validUsername}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {saving ? 'Saving…' : mode === 'create' ? 'Create user' : 'Save changes'}
                  </button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}

function ConfirmDialog({
  open,
  username,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  username: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!open) return null;
  const Dialog = window.HeadlessUI?.Dialog;
  const Transition = window.HeadlessUI?.Transition;
  if (!Dialog || !Transition) {
    return null;
  }

  return (
    <Transition appear show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onCancel}>
        <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100" leave="ease-in duration-150" leaveFrom="opacity-100" leaveTo="opacity-0">
          <div className="fixed inset-0 bg-slate-900/50" />
        </Transition.Child>
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100" leave="ease-in duration-150" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95">
            <Dialog.Panel className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
              <Dialog.Title className="text-lg font-semibold text-slate-900">Delete user</Dialog.Title>
              <p className="mt-2 text-sm text-slate-600">Are you sure you want to delete <strong>@{username}</strong>? This cannot be undone.</p>
              <div className="mt-6 flex justify-end gap-3">
                <button type="button" onClick={onCancel} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">Cancel</button>
                <button type="button" onClick={onConfirm} disabled={busy} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">{busy ? 'Deleting…' : 'Delete user'}</button>
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}

function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [totalUsageBytes, setTotalUsageBytes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [services, setServices] = useState<ServiceRecord[]>([]);
  const [search, setSearch] = useState('');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [modalSaving, setModalSaving] = useState(false);
  const [modalError, setModalError] = useState('');
  const [formValues, setFormValues] = useState<UserFormValues>({
    username: '',
    limitGb: '',
    durationDays: '',
    renewDays: '',
    serviceId: '',
    resetUsed: false,
  });

  const [deleteTarget, setDeleteTarget] = useState<UserRecord | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const stats = useMemo(() => {
    const disabled = users.filter((user) => user.disabled).length;
    return { totalUsers: users.length, disabledUsers: disabled, totalUsageBytes };
  }, [users, totalUsageBytes]);

  const displayedUsers = useMemo(() => {
    const filtered = users.filter((user) => user.username.toLowerCase().includes(search.trim().toLowerCase()));
    return [...filtered].sort((a, b) => {
      const direction = sortDirection === 'asc' ? 1 : -1;
      return a.username.localeCompare(b.username) * direction;
    });
  }, [users, search, sortDirection]);

  const reloadUsers = async () => {
    const res = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
    if (res.status === 401) {
      window.location.replace('/web/login');
      return;
    }
    if (!res.ok) throw new Error('Failed to load users');
    const data = (await res.json()) as UsersResponse;
    setUsers(Array.isArray(data.users) ? data.users : []);
    setTotalUsageBytes(Number(data.total_used_bytes || 0));
  };

  useEffect(() => {
    const load = async () => {
      try {
        const [meRes, usersRes, servicesRes] = await Promise.all([
          fetch('/api/v1/web/me', { credentials: 'same-origin' }),
          fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' }),
          fetch('/api/v1/web/services', { credentials: 'same-origin' }),
        ]);
        if (!meRes.ok || usersRes.status === 401) {
          window.location.replace('/web/login');
          return;
        }
        if (!usersRes.ok) throw new Error('Failed users fetch');
        const usersData = (await usersRes.json()) as UsersResponse;
        const servicesData = servicesRes.ok ? ((await servicesRes.json()) as ServiceRecord[]) : [];
        setUsers(Array.isArray(usersData.users) ? usersData.users : []);
        setTotalUsageBytes(Number(usersData.total_used_bytes || 0));
        setServices(Array.isArray(servicesData) ? servicesData : []);
      } catch {
        setError('Unable to load users right now.');
      } finally {
        setLoading(false);
      }
    };

    void load();
  }, []);

  const logout = async () => {
    try {
      await fetch('/api/v1/web/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.replace('/web/login');
    }
  };

  const openCreateModal = () => {
    setModalMode('create');
    setFormValues({ username: '', limitGb: '', durationDays: '', renewDays: '', serviceId: '', resetUsed: false });
    setModalError('');
    setModalOpen(true);
  };

  const openEditModal = (user: UserRecord) => {
    setModalMode('edit');
    setFormValues({ username: user.username, limitGb: '', durationDays: '', renewDays: '', serviceId: user.service_id ? String(user.service_id) : '', resetUsed: false });
    setModalError('');
    setModalOpen(true);
  };

  const submitUserModal = async () => {
    setModalError('');
    const limitGbNumber = Number(formValues.limitGb || '0');
    const durationDaysNumber = Number(formValues.durationDays || '0');
    const renewDaysNumber = Number(formValues.renewDays || '0');

    if (!formValues.username.trim()) {
      setModalError('Username is required.');
      return;
    }
    if (!Number.isFinite(limitGbNumber) || limitGbNumber < 0) {
      setModalError('Traffic limit must be a non-negative number.');
      return;
    }

    setModalSaving(true);
    try {
      if (modalMode === 'create') {
        if (!Number.isFinite(durationDaysNumber) || durationDaysNumber < 0) {
          setModalError('Duration days must be a non-negative number.');
          return;
        }
        const createRes = await fetch('/api/v1/web/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            username: formValues.username.trim(),
            limit_bytes: Math.round(limitGbNumber * 1024 * 1024 * 1024),
            duration_days: Math.round(durationDaysNumber),
            service_id: formValues.serviceId ? Number(formValues.serviceId) : null,
          }),
        });
        const payload = await createRes.json().catch(() => ({}));
        if (!createRes.ok) {
          setModalError(payload.detail || 'Could not create user.');
          return;
        }
      } else {
        if (!Number.isFinite(renewDaysNumber) || renewDaysNumber < 0) {
          setModalError('Renew days must be a non-negative number.');
          return;
        }
        const editRes = await fetch(`/api/v1/web/users/${encodeURIComponent(formValues.username)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            limit_bytes: Math.round(limitGbNumber * 1024 * 1024 * 1024),
            renew_days: renewDaysNumber > 0 ? Math.round(renewDaysNumber) : null,
            reset_used: formValues.resetUsed,
            service_id: formValues.serviceId ? Number(formValues.serviceId) : null,
          }),
        });
        const payload = await editRes.json().catch(() => ({}));
        if (!editRes.ok) {
          setModalError(payload.detail || 'Could not update user.');
          return;
        }
      }

      setModalOpen(false);
      await reloadUsers();
    } catch {
      setModalError('Request failed. Please try again.');
    } finally {
      setModalSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(deleteTarget.username)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(payload.detail || 'Could not delete user.');
        return;
      }
      setDeleteTarget(null);
      await reloadUsers();
    } catch {
      setError('Could not delete user. Please try again.');
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <LayoutShell title="Users" onAddUser={openCreateModal} onLogout={logout}>
      <section className="mb-6 grid gap-4 sm:grid-cols-3">
        <article className="rounded-xl bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Total users</p><p className="mt-2 text-2xl font-semibold">{numberFormatter.format(stats.totalUsers)}</p></article>
        <article className="rounded-xl bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Disabled users</p><p className="mt-2 text-2xl font-semibold">{numberFormatter.format(stats.disabledUsers)}</p></article>
        <article className="rounded-xl bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Total usage</p><p className="mt-2 text-2xl font-semibold">{formatBytes(stats.totalUsageBytes)}</p></article>
      </section>

      {error ? <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}

      <UsersTable
        users={displayedUsers}
        loading={loading}
        search={search}
        sortDirection={sortDirection}
        onSearchChange={setSearch}
        onToggleSort={() => setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
        onEdit={openEditModal}
        onDelete={setDeleteTarget}
      />

      <UserModal
        open={modalOpen}
        mode={modalMode}
        services={services}
        values={formValues}
        saving={modalSaving}
        error={modalError}
        onChange={(patch) => setFormValues((prev) => ({ ...prev, ...patch }))}
        onClose={() => setModalOpen(false)}
        onSubmit={submitUserModal}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        username={deleteTarget?.username || ''}
        busy={deleteBusy}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
      />
    </LayoutShell>
  );
}

const rootNode = document.getElementById('root');
if (rootNode) {
  ReactDOM.createRoot(rootNode).render(<UsersPage />);
}
