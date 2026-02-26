import type { UserRecord } from '/static/types.ts';
import { formatBytes, parseDate } from '/static/utils.ts';

type SortKey = 'username' | 'plan_limit_bytes' | 'used_bytes' | 'expire_at';

type UsersTableProps = {
  users: UserRecord[];
  loading: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  onEdit: (user: UserRecord) => void;
  onDelete: (user: UserRecord) => void;
};

const { useMemo, useState } = React;

export function UsersTable({ users, loading, search, onSearchChange, onEdit, onDelete }: UsersTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('username');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');

  const filteredUsers = useMemo(
    () => users.filter((user) => user.username.toLowerCase().includes(search.trim().toLowerCase())),
    [search, users],
  );

  const sortedUsers = useMemo(() => {
    const sorted = [...filteredUsers].sort((a, b) => {
      const direction = sortDirection === 'asc' ? 1 : -1;
      if (sortKey === 'expire_at') {
        return direction * ((a.expire_at || '').localeCompare(b.expire_at || ''));
      }
      const left = a[sortKey];
      const right = b[sortKey];
      if (typeof left === 'number' && typeof right === 'number') return direction * (left - right);
      return direction * String(left).localeCompare(String(right));
    });
    return sorted;
  }, [filteredUsers, sortDirection, sortKey]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setSortDirection('asc');
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search by username"
          aria-label="Search users"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-indigo-200 transition focus:ring-2 sm:max-w-sm"
        />
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
          <thead>
            <tr>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">
                <button type="button" onClick={() => toggleSort('username')}>Username</button>
              </th>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">
                <button type="button" onClick={() => toggleSort('plan_limit_bytes')}>Plan limit</button>
              </th>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">
                <button type="button" onClick={() => toggleSort('used_bytes')}>Used</button>
              </th>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">
                <button type="button" onClick={() => toggleSort('expire_at')}>Expires at</button>
              </th>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">Status</th>
              <th className="border-b border-slate-200 px-3 py-3 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td className="px-3 py-6 text-slate-500" colSpan={6}>Loading users…</td></tr>
            ) : sortedUsers.length === 0 ? (
              <tr><td className="px-3 py-6 text-slate-500" colSpan={6}>No users found for this search.</td></tr>
            ) : (
              sortedUsers.map((user) => (
                <tr key={user.username} className="hover:bg-slate-50">
                  <td className="border-b border-slate-100 px-3 py-3">{user.username}</td>
                  <td className="border-b border-slate-100 px-3 py-3">{formatBytes(user.plan_limit_bytes)}</td>
                  <td className="border-b border-slate-100 px-3 py-3">{formatBytes(user.used_bytes)}</td>
                  <td className="border-b border-slate-100 px-3 py-3">{parseDate(user.expire_at)}</td>
                  <td className="border-b border-slate-100 px-3 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${user.disabled ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                      {user.disabled ? 'Disabled' : 'Active'}
                    </span>
                  </td>
                  <td className="border-b border-slate-100 px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button type="button" onClick={() => onEdit(user)} className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium">Edit</button>
                      <button type="button" onClick={() => onDelete(user)} className="rounded-md border border-red-300 px-2.5 py-1.5 text-xs font-medium text-red-700">Delete</button>
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
