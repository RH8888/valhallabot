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

type UserModalValues = {
  username: string;
  limitGb: string;
  durationDays: string;
  serviceId: string;
};

type UserModalProps = {
  isOpen: boolean;
  mode: 'add' | 'edit';
  services: ServiceRecord[];
  initialValues: UserModalValues;
  saving: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (values: UserModalValues) => Promise<void>;
};

type ConfirmDialogProps = {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
};

type UsersTableProps = {
  users: UserRecord[];
  loading: boolean;
  search: string;
  sort: 'asc' | 'desc';
  onSearchChange: (value: string) => void;
  onSortToggle: () => void;
  onEdit: (user: UserRecord) => void;
  onDelete: (user: UserRecord) => void;
};

declare const HeadlessUI: {
  Dialog: React.ComponentType<Record<string, unknown>>;
  DialogPanel: React.ComponentType<Record<string, unknown>>;
  DialogTitle: React.ComponentType<Record<string, unknown>>;
  Description: React.ComponentType<Record<string, unknown>>;
};

const { useEffect, useMemo, useState } = React;
const { Dialog, DialogPanel, DialogTitle, Description } = HeadlessUI;

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
  subtitle,
  onLogout,
  onAddUser,
  children,
}: {
  title: string;
  subtitle: string;
  onLogout: () => void;
  onAddUser: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto flex min-h-screen w-full max-w-[1400px] flex-col md:flex-row">
        <aside className="border-b border-slate-200 bg-white px-4 py-4 md:w-64 md:border-b-0 md:border-r md:px-6 md:py-8">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Valhalla Admin</p>
          <nav className="mt-4 space-y-2">
            <a href="/web/users" className="block rounded-lg bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700">Manage Users</a>
          </nav>
          <button
            type="button"
            onClick={onLogout}
            className="mt-6 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Logout
          </button>
        </aside>

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <header className="mb-6 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 sm:p-6 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
              <p className="mt-2 text-sm text-slate-600">{subtitle}</p>
            </div>
            <button
              type="button"
              onClick={onAddUser}
              className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500"
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

function UsersTable({ users, loading, search, sort, onSearchChange, onSortToggle, onEdit, onDelete }: UsersTableProps) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search users"
          aria-label="Search users"
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 sm:max-w-sm"
        />
        <button
          type="button"
          onClick={onSortToggle}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Sort: Username {sort === 'asc' ? 'A-Z' : 'Z-A'}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-3">Username</th>
              <th className="px-3 py-3">Plan limit</th>
              <th className="px-3 py-3">Used</th>
              <th className="px-3 py-3">Expires at</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white text-slate-700">
            {loading ? (
              <tr>
                <td className="px-3 py-6 text-center text-slate-500" colSpan={6}>Loading users...</td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td className="px-3 py-6 text-center text-slate-500" colSpan={6}>No users match your search.</td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.username}>
                  <td className="px-3 py-3 font-medium text-slate-900">{user.username}</td>
                  <td className="px-3 py-3">{formatBytes(user.plan_limit_bytes)}</td>
                  <td className="px-3 py-3">{formatBytes(user.used_bytes)}</td>
                  <td className="px-3 py-3">{parseDate(user.expire_at)}</td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${user.disabled ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700'}`}>
                      {user.disabled ? 'Disabled' : 'Active'}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex gap-2">
                      <button type="button" onClick={() => onEdit(user)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">Edit</button>
                      <button type="button" onClick={() => onDelete(user)} className="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50">Delete</button>
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

function UserModal({ isOpen, mode, services, initialValues, saving, error, onClose, onSubmit }: UserModalProps) {
  const [values, setValues] = useState<UserModalValues>(initialValues);

  useEffect(() => {
    setValues(initialValues);
  }, [initialValues, isOpen]);

  const usernameDisabled = mode === 'edit';
  const title = mode === 'add' ? 'Add user' : `Edit ${initialValues.username}`;
  const actionLabel = saving ? 'Saving...' : mode === 'add' ? 'Create user' : 'Save changes';

  const hasValidationError = !values.username.trim() || Number(values.limitGb || '0') < 0 || Number(values.durationDays || '0') < 0;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (hasValidationError || saving) return;
    await onSubmit(values);
  };

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-slate-900/50" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 sm:px-6">
            <DialogTitle className="text-lg font-semibold text-slate-900">{title}</DialogTitle>
            <button type="button" onClick={onClose} className="rounded-md border border-slate-300 px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-50">Close</button>
          </div>

          <form onSubmit={submit} className="space-y-4 px-4 py-4 sm:px-6 sm:py-5">
            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Username</span>
              <input
                value={values.username}
                onChange={(event) => setValues((prev) => ({ ...prev, username: event.target.value }))}
                disabled={usernameDisabled}
                required
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-100"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Traffic limit (GB)</span>
              <input
                type="number"
                min="0"
                value={values.limitGb}
                onChange={(event) => setValues((prev) => ({ ...prev, limitGb: event.target.value }))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Duration (days)</span>
              <input
                type="number"
                min="0"
                value={values.durationDays}
                onChange={(event) => setValues((prev) => ({ ...prev, durationDays: event.target.value }))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm font-medium text-slate-700">Service</span>
              <select
                value={values.serviceId}
                onChange={(event) => setValues((prev) => ({ ...prev, serviceId: event.target.value }))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
              >
                <option value="">No service</option>
                {services.map((service) => <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>)}
              </select>
            </label>

            {error ? <p className="text-sm text-rose-600">{error}</p> : null}

            <footer className="flex justify-end gap-3 border-t border-slate-200 pt-4">
              <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
              <button type="submit" disabled={saving || hasValidationError} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60 hover:bg-indigo-500">{actionLabel}</button>
            </footer>
          </form>
        </DialogPanel>
      </div>
    </Dialog>
  );
}

function ConfirmDialog({ isOpen, title, message, confirmLabel = 'Delete', busy, onClose, onConfirm }: ConfirmDialogProps) {
  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-slate-900/50" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-5 shadow-xl">
          <DialogTitle className="text-lg font-semibold text-slate-900">{title}</DialogTitle>
          <Description className="mt-2 text-sm text-slate-600">{message}</Description>
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
            <button type="button" onClick={() => void onConfirm()} disabled={busy} className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60 hover:bg-rose-500">
              {busy ? 'Deleting...' : confirmLabel}
            </button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}

function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [services, setServices] = useState<ServiceRecord[]>([]);
  const [sort, setSort] = useState<'asc' | 'desc'>('asc');

  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userModalMode, setUserModalMode] = useState<'add' | 'edit'>('add');
  const [selectedUser, setSelectedUser] = useState<UserRecord | null>(null);
  const [savingUser, setSavingUser] = useState(false);
  const [modalError, setModalError] = useState('');

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingUser, setDeletingUser] = useState(false);

  const reloadUsers = async () => {
    const usersRes = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
    if (usersRes.status === 401) {
      window.location.replace('/web/login');
      return;
    }
    if (!usersRes.ok) throw new Error('load users failed');
    const usersData = (await usersRes.json()) as UsersResponse;
    setUsers(Array.isArray(usersData.users) ? usersData.users : []);
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
        if (!usersRes.ok) throw new Error('load failed');

        const usersData = (await usersRes.json()) as UsersResponse;
        const serviceData = servicesRes.ok ? ((await servicesRes.json()) as ServiceRecord[]) : [];
        setUsers(Array.isArray(usersData.users) ? usersData.users : []);
        setServices(Array.isArray(serviceData) ? serviceData : []);
      } catch {
        setError('Unable to load users right now.');
      } finally {
        setLoading(false);
      }
    };

    void boot();
  }, []);

  const filteredUsers = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matched = users.filter((user) => user.username.toLowerCase().includes(needle));
    return matched.sort((a, b) => (sort === 'asc' ? a.username.localeCompare(b.username) : b.username.localeCompare(a.username)));
  }, [users, search, sort]);

  const openAddModal = () => {
    setSelectedUser(null);
    setUserModalMode('add');
    setModalError('');
    setUserModalOpen(true);
  };

  const openEditModal = (user: UserRecord) => {
    setSelectedUser(user);
    setUserModalMode('edit');
    setModalError('');
    setUserModalOpen(true);
  };

  const closeUserModal = () => {
    setUserModalOpen(false);
    setSavingUser(false);
    setModalError('');
  };

  const onSubmitUser = async (values: UserModalValues) => {
    setModalError('');
    setSavingUser(true);

    const limitGbNumber = Number(values.limitGb || '0');
    const durationDaysNumber = Number(values.durationDays || '0');

    if (!Number.isFinite(limitGbNumber) || limitGbNumber < 0) {
      setModalError('Traffic limit must be a non-negative number.');
      setSavingUser(false);
      return;
    }
    if (!Number.isFinite(durationDaysNumber) || durationDaysNumber < 0) {
      setModalError('Duration days must be a non-negative number.');
      setSavingUser(false);
      return;
    }

    try {
      if (userModalMode === 'add') {
        const res = await fetch('/api/v1/web/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            username: values.username.trim(),
            limit_bytes: Math.round(limitGbNumber * 1024 * 1024 * 1024),
            duration_days: Math.round(durationDaysNumber),
            service_id: values.serviceId ? Number(values.serviceId) : null,
          }),
        });
        if (res.status === 401) {
          window.location.replace('/web/login');
          return;
        }
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          setModalError(payload.detail || 'Could not create user.');
          return;
        }
      } else if (selectedUser) {
        const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            limit_bytes: Math.round(limitGbNumber * 1024 * 1024 * 1024),
            renew_days: Math.round(durationDaysNumber),
            service_id: values.serviceId ? Number(values.serviceId) : null,
          }),
        });
        if (!res.ok) {
          setModalError('Could not update user.');
          return;
        }
      }

      await reloadUsers();
      closeUserModal();
    } catch {
      setModalError('Unable to save user right now.');
    } finally {
      setSavingUser(false);
    }
  };

  const openDeleteDialog = (user: UserRecord) => {
    setSelectedUser(user);
    setDeleteDialogOpen(true);
    setError('');
  };

  const closeDeleteDialog = () => {
    setDeleteDialogOpen(false);
    setDeletingUser(false);
  };

  const confirmDelete = async () => {
    if (!selectedUser) return;
    setDeletingUser(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (res.status === 404) {
        setError('Delete endpoint is not available in this backend yet.');
        return;
      }
      if (!res.ok) {
        setError('Could not delete user.');
        return;
      }
      await reloadUsers();
      closeDeleteDialog();
    } catch {
      setError('Could not delete user.');
    } finally {
      setDeletingUser(false);
    }
  };

  const logout = async () => {
    try {
      await fetch('/api/v1/web/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.replace('/web/login');
    }
  };

  const initialValues: UserModalValues = selectedUser
    ? {
        username: selectedUser.username,
        limitGb: String(Math.round((selectedUser.plan_limit_bytes / 1024 / 1024 / 1024) * 100) / 100),
        durationDays: '',
        serviceId: selectedUser.service_id ? String(selectedUser.service_id) : '',
      }
    : { username: '', limitGb: '', durationDays: '', serviceId: '' };

  return (
    <LayoutShell
      title="Manage Users"
      subtitle="Search, edit, and manage user quotas in one focused workspace."
      onAddUser={openAddModal}
      onLogout={() => void logout()}
    >
      {error ? <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
      <UsersTable
        users={filteredUsers}
        loading={loading}
        search={search}
        sort={sort}
        onSearchChange={setSearch}
        onSortToggle={() => setSort((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
        onEdit={openEditModal}
        onDelete={openDeleteDialog}
      />

      <UserModal
        isOpen={userModalOpen}
        mode={userModalMode}
        services={services}
        initialValues={initialValues}
        saving={savingUser}
        error={modalError}
        onClose={closeUserModal}
        onSubmit={onSubmitUser}
      />

      <ConfirmDialog
        isOpen={deleteDialogOpen}
        title="Delete user"
        message={`Are you sure you want to delete ${selectedUser?.username || 'this user'}? This action cannot be undone.`}
        busy={deletingUser}
        onClose={closeDeleteDialog}
        onConfirm={confirmDelete}
      />
    </LayoutShell>
  );
}

const rootNode = document.getElementById('root');
if (rootNode) {
  ReactDOM.createRoot(rootNode).render(<UsersPage />);
}
