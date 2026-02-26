import { LayoutShell } from '../components/LayoutShell.tsx';
import { UsersTable } from '../components/UsersTable.tsx';
import { UserModal } from '../components/UserModal.tsx';
import { ConfirmDialog } from '../components/ConfirmDialog.tsx';
import type { ServiceRecord, UserFormValues, UserRecord, UsersResponse } from '../types.ts';

const { useEffect, useMemo, useState } = React;
const numberFormatter = new Intl.NumberFormat();

function emptyFormValues(): UserFormValues {
  return { username: '', limitGb: '', durationDays: '', serviceId: '' };
}

export function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [services, setServices] = useState<ServiceRecord[]>([]);
  const [totalUsageBytes, setTotalUsageBytes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  const [userModalOpen, setUserModalOpen] = useState(false);
  const [userModalMode, setUserModalMode] = useState<'create' | 'edit'>('create');
  const [formValues, setFormValues] = useState<UserFormValues>(emptyFormValues());
  const [activeUsername, setActiveUsername] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<UserRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  const stats = useMemo(() => {
    const disabled = users.filter((user) => user.disabled).length;
    return { totalUsers: users.length, disabled, totalUsage: totalUsageBytes };
  }, [users, totalUsageBytes]);

  const reloadUsers = async () => {
    const usersRes = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
    if (usersRes.status === 401) {
      window.location.replace('/web/login');
      return;
    }
    if (!usersRes.ok) throw new Error('load users failed');
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
        const [usersRes, servicesRes] = await Promise.all([
          fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' }),
          fetch('/api/v1/web/services', { credentials: 'same-origin' }),
        ]);
        if (!usersRes.ok) throw new Error('load users failed');
        const usersData = (await usersRes.json()) as UsersResponse;
        const serviceData = servicesRes.ok ? ((await servicesRes.json()) as ServiceRecord[]) : [];
        setUsers(Array.isArray(usersData.users) ? usersData.users : []);
        setTotalUsageBytes(Number(usersData.total_used_bytes || 0));
        setServices(Array.isArray(serviceData) ? serviceData : []);
      } catch {
        setError('Unable to load users right now.');
      } finally {
        setLoading(false);
      }
    };
    void boot();
  }, []);

  const openCreateModal = () => {
    setUserModalMode('create');
    setActiveUsername(null);
    setFormValues(emptyFormValues());
    setError('');
    setUserModalOpen(true);
  };

  const openEditModal = (user: UserRecord) => {
    setUserModalMode('edit');
    setActiveUsername(user.username);
    setFormValues({
      username: user.username,
      limitGb: '',
      durationDays: '',
      serviceId: user.service_id ? String(user.service_id) : '',
    });
    setError('');
    setUserModalOpen(true);
  };

  const validateForm = (): string => {
    if (!formValues.username.trim()) return 'Username is required.';
    if (formValues.limitGb && (!Number.isFinite(Number(formValues.limitGb)) || Number(formValues.limitGb) < 0)) return 'Traffic limit must be a non-negative number.';
    if (formValues.durationDays && (!Number.isFinite(Number(formValues.durationDays)) || Number(formValues.durationDays) < 0)) return 'Duration/renew days must be a non-negative number.';
    return '';
  };

  const saveUser = async (event: React.FormEvent) => {
    event.preventDefault();
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError('');
    try {
      if (userModalMode === 'create') {
        const res = await fetch('/api/v1/web/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            username: formValues.username.trim(),
            limit_bytes: Math.round(Number(formValues.limitGb || '0') * 1024 * 1024 * 1024),
            duration_days: Math.round(Number(formValues.durationDays || '0')),
            service_id: formValues.serviceId ? Number(formValues.serviceId) : null,
          }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          setError(payload.detail || 'Could not create user.');
          return;
        }
      } else {
        const payload: Record<string, unknown> = {};
        if (formValues.limitGb) payload.limit_bytes = Math.round(Number(formValues.limitGb) * 1024 * 1024 * 1024);
        if (formValues.durationDays) payload.renew_days = Number(formValues.durationDays);
        payload.service_id = formValues.serviceId ? Number(formValues.serviceId) : null;

        const res = await fetch(`/api/v1/web/users/${encodeURIComponent(activeUsername || '')}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          setError('Could not update user.');
          return;
        }
      }
      setUserModalOpen(false);
      setFormValues(emptyFormValues());
      await reloadUsers();
    } catch {
      setError('Could not save user. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const deleteUser = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setError('');
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(deleteTarget.username)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        setError('Could not delete user.');
        return;
      }
      setDeleteTarget(null);
      await reloadUsers();
    } catch {
      setError('Could not delete user.');
    } finally {
      setDeleting(false);
    }
  };

  const logout = async () => {
    try {
      await fetch('/api/v1/web/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.replace('/web/login');
    }
  };

  return (
    <LayoutShell
      title="Manage users"
      subtitle="Search, edit and monitor users from a dedicated admin page."
      primaryActionLabel="Add user"
      onPrimaryAction={openCreateModal}
      onLogout={logout}
    >
      <section className="mb-6 grid gap-4 sm:grid-cols-3">
        <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Total users</p><strong className="mt-2 block text-2xl">{numberFormatter.format(stats.totalUsers)}</strong></article>
        <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Disabled users</p><strong className="mt-2 block text-2xl">{numberFormatter.format(stats.disabled)}</strong></article>
        <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><p className="text-sm text-slate-500">Total usage</p><strong className="mt-2 block text-2xl">{(stats.totalUsage / (1024 ** 3)).toFixed(2)} GB</strong></article>
      </section>

      {error ? <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}

      <UsersTable
        users={users}
        loading={loading}
        search={search}
        onSearchChange={setSearch}
        onEdit={openEditModal}
        onDelete={(user) => setDeleteTarget(user)}
      />

      <UserModal
        open={userModalOpen}
        mode={userModalMode}
        title={userModalMode === 'create' ? 'Add user' : `Edit @${activeUsername}`}
        services={services}
        values={formValues}
        saving={saving}
        error={error}
        onOpenChange={setUserModalOpen}
        onChange={setFormValues}
        onSubmit={saveUser}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete user"
        description={`Are you sure you want to delete ${deleteTarget?.username || 'this user'}? This action cannot be undone.`}
        busy={deleting}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        onConfirm={deleteUser}
      />
    </LayoutShell>
  );
}
