type PageMode = 'login' | 'users' | 'home' | 'services' | 'nodes' | 'hosts' | 'admins' | 'settings';

type UserRecord = {
  username: string;
  plan_limit_bytes: number;
  used_bytes: number;
  expire_at?: string | null;
  service_id?: number | null;
  disabled: boolean;
  owner_id?: number;
};

type UsersResponse = {
  total: number;
  total_used_bytes?: number;
  users: UserRecord[];
};

type PanelUsageRecord = {
  panel_id: number;
  panel_name: string;
  panel_type?: string | null;
  panel_url?: string | null;
  used_bytes: number;
};

type PanelUsageResponse = {
  total_used_bytes?: number;
  panels: PanelUsageRecord[];
};

type ServiceRecord = {
  id: number;
  name: string;
};

type SubscriptionResponse = {
  urls: string[];
  qr_data_uris: string[];
};

const { useEffect, useMemo, useState, useCallback, useRef } = React;
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
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function isUserExpired(expireAt?: string | null): boolean {
  if (!expireAt) return false;
  const d = new Date(expireAt);
  return !isNaN(d.getTime()) && d < new Date();
}

function getUserStatus(user: UserRecord): 'Expired' | 'Disabled' | 'Active' {
  if (isUserExpired(user.expire_at)) return 'Expired';
  if (user.disabled) return 'Disabled';
  return 'Active';
}

function isUserExpiringSoon(expireAt?: string | null): boolean {
  if (!expireAt) return false;
  const d = new Date(expireAt);
  const soon = new Date();
  soon.setDate(soon.getDate() + 7); // 7 days window
  return !isNaN(d.getTime()) && d > new Date() && d < soon;
}

// Styling Constants
const inputClass = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/10 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-brand-400 dark:focus:ring-brand-400/10';
const btnBase = 'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50';
const btnPrimary = `${btnBase} bg-brand-600 text-white hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-600`;
const btnSecondary = `${btnBase} border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700`;
const btnGhost = `${btnBase} text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800`;
const cardClass = 'rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900';

function Icon({ name, className = "" }: { name: string; className?: string }) {
  return <i className={`${name} ${className}`} />;
}

// Components

function SidebarItem({
  icon,
  label,
  active,
  collapsed,
  onClick,
  href
}: {
  icon: string;
  label: string;
  active?: boolean;
  collapsed?: boolean;
  onClick?: () => void;
  href: string;
}) {
  return (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        onClick?.();
      }}
      className={`group flex items-center gap-3 rounded-lg px-3 py-2 transition-colors ${
        active
          ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400'
          : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200'
      }`}
      title={collapsed ? label : undefined}
    >
      <Icon name={icon} className={`text-lg ${active ? 'text-brand-600 dark:text-brand-400' : 'text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-300'}`} />
      {!collapsed && <span className="text-sm font-medium">{label}</span>}
    </a>
  );
}

function Sidebar({
  collapsed,
  mobileOpen,
  setMobileOpen,
  currentPath,
  onNavigate
}: {
  collapsed: boolean;
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
  currentPath: string;
  onNavigate: (path: string) => void;
}) {
  const groups = [
    {
      title: 'Dashboard',
      items: [
        { label: 'Home', icon: 'fa-solid fa-house', path: '/web/home' },
      ]
    },
    {
      title: 'Management',
      items: [
        { label: 'Users', icon: 'fa-solid fa-users', path: '/web/users' },
        { label: 'Services', icon: 'fa-solid fa-layer-group', path: '/web/services' },
        { label: 'Nodes', icon: 'fa-solid fa-server', path: '/web/nodes' },
        { label: 'Hosts', icon: 'fa-solid fa-network-wired', path: '/web/hosts' },
      ]
    },
    {
      title: 'System',
      items: [
        { label: 'Admins', icon: 'fa-solid fa-user-shield', path: '/web/admins' },
        { label: 'Settings', icon: 'fa-solid fa-gear', path: '/web/settings' },
      ]
    }
  ];

  const sidebarContent = (
    <div className="flex h-full flex-col gap-4 py-4">
      <div className={`px-4 pb-2 transition-opacity ${collapsed ? 'opacity-0' : 'opacity-100'}`}>
        <span className="text-xl font-bold tracking-tight text-slate-900 dark:text-white">Valhalla</span>
      </div>

      <nav className="flex-1 space-y-6 px-3">
        {groups.map((group) => (
          <div key={group.title}>
            {!collapsed && (
              <h3 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                {group.title}
              </h3>
            )}
            <div className="space-y-1">
              {group.items.map((item) => (
                <SidebarItem
                  key={item.path}
                  icon={item.icon}
                  label={item.label}
                  href={item.path}
                  active={currentPath === item.path}
                  collapsed={collapsed}
                  onClick={() => {
                    onNavigate(item.path);
                    setMobileOpen(false);
                  }}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="px-3">
        <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
          {!collapsed ? (
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-brand-500 text-white flex items-center justify-center font-bold">A</div>
              <div className="flex-1 min-w-0">
                <p className="truncate text-xs font-medium text-slate-900 dark:text-white">Admin User</p>
                <p className="truncate text-[10px] text-slate-500">admin@valhalla.io</p>
              </div>
            </div>
          ) : (
            <div className="h-8 w-8 rounded-full bg-brand-500 text-white flex items-center justify-center font-bold mx-auto">A</div>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 hidden border-r border-slate-200 bg-white transition-all duration-300 dark:border-slate-800 dark:bg-slate-900 md:block ${
          collapsed ? 'w-16' : 'w-64'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Mobile Drawer */}
      <div
        className={`fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm transition-opacity md:hidden ${
          mobileOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={() => setMobileOpen(false)}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-white transition-transform duration-300 dark:bg-slate-900 md:hidden ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>
    </>
  );
}

function TopBar({
  onToggleSidebar,
  onToggleTheme,
  theme,
  onLogout
}: {
  onToggleSidebar: () => void;
  onToggleTheme: () => void;
  theme: 'dark' | 'light';
  onLogout: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex items-center gap-4">
        <button
          onClick={onToggleSidebar}
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          <Icon name="fa-solid fa-bars" className="text-lg" />
        </button>

        <div className="relative hidden max-w-md md:block">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400">
            <Icon name="fa-solid fa-magnifying-glass" className="text-xs" />
          </div>
          <input
            type="text"
            className="w-64 rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-10 pr-3 text-xs outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            placeholder="Search everything..."
            readOnly
          />
          <div className="absolute inset-y-0 right-0 flex items-center pr-3">
            <kbd className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-400 shadow-sm dark:bg-slate-700">Ctrl K</kbd>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onToggleTheme}
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          title="Toggle Theme"
        >
          <Icon name={theme === 'dark' ? 'fa-solid fa-sun' : 'fa-solid fa-moon'} />
        </button>
        <button
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          title="Notifications"
        >
          <Icon name="fa-regular fa-bell" />
        </button>
        <div className="mx-2 h-6 w-px bg-slate-200 dark:bg-slate-700" />

        <div className="flex items-center gap-3 pl-2">
          <div className="hidden flex-col items-end sm:flex">
            <span className="text-xs font-semibold text-slate-900 dark:text-white">Admin</span>
            <span className="text-[10px] text-slate-500 uppercase tracking-tighter">Superuser</span>
          </div>
          <div className="group relative cursor-pointer">
            <div className="h-9 w-9 rounded-full bg-slate-100 p-0.5 ring-2 ring-slate-200 transition-all hover:ring-brand-500 dark:bg-slate-800 dark:ring-slate-700">
              <img src="https://ui-avatars.com/api/?name=Admin&background=0ea5e9&color=fff" className="h-full w-full rounded-full" alt="Avatar" />
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function InsightCard({ label, value, icon, trend, trendUp, onClick, className }: { label: string; value: string | number; icon: string; trend?: string; trendUp?: boolean; onClick?: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${cardClass} p-5 text-left ${onClick ? 'cursor-pointer hover:border-brand-400 hover:shadow-md' : ''} ${className || ''}`}
    >
      <div className="flex items-center justify-between">
        <div className="h-10 w-10 rounded-lg bg-slate-50 flex items-center justify-center text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <Icon name={icon} className="text-lg" />
        </div>
        {trend && (
          <span className={`text-xs font-medium ${trendUp ? 'text-emerald-600' : 'text-rose-600'}`}>
            {trend} <Icon name={trendUp ? 'fa-solid fa-arrow-up' : 'fa-solid fa-arrow-down'} className="ml-0.5 text-[10px]" />
          </span>
        )}
      </div>
      <div className="mt-4">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
        <h4 className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{value}</h4>
      </div>
    </button>
  );
}

function PanelUsageModal({
  open,
  onClose,
  loading,
  totalUsedBytes,
  panels,
}: {
  open: boolean;
  onClose: () => void;
  loading: boolean;
  totalUsedBytes: number;
  panels: PanelUsageRecord[];
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className={cardClass + " w-full max-w-3xl p-6 shadow-2xl"} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-xl font-bold text-slate-900 dark:text-white">Lifetime panel usage</h3>
            <p className="text-xs text-slate-500">Usage remains visible even if the panel is no longer assigned to any active service.</p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
            <Icon name="fa-solid fa-xmark" className="text-xl" />
          </button>
        </div>

        <div className="mb-4 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">
          <span className="text-slate-500">Total lifetime usage: </span>
          <span className="font-semibold text-slate-900 dark:text-white">{formatBytes(totalUsedBytes)}</span>
        </div>

        {loading ? (
          <div className="py-12 text-center text-slate-500">Loading panel usage...</div>
        ) : panels.length === 0 ? (
          <div className="py-12 text-center text-slate-500">No panel usage found.</div>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50 dark:bg-slate-900">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Panel</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">Type</th>
                  <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">URL</th>
                  <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-slate-500">Used</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {panels.map((panel) => (
                  <tr key={panel.panel_id}>
                    <td className="px-4 py-2 font-medium text-slate-900 dark:text-white">{panel.panel_name}</td>
                    <td className="px-4 py-2 text-slate-600 dark:text-slate-300">{panel.panel_type || '-'}</td>
                    <td className="px-4 py-2 text-slate-500">{panel.panel_url || '-'}</td>
                    <td className="px-4 py-2 text-right font-semibold text-slate-900 dark:text-white">{formatBytes(panel.used_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex h-[calc(100vh-12rem)] flex-col items-center justify-center text-center">
      <div className="mb-4 rounded-full bg-brand-50 p-6 dark:bg-brand-500/10">
        <Icon name="fa-solid fa-rocket" className="text-4xl text-brand-600 dark:text-brand-400" />
      </div>
      <h2 className="text-2xl font-bold text-slate-900 dark:text-white">{title}</h2>
      <p className="mt-2 max-w-sm text-slate-500">We're working hard to bring you this feature. Stay tuned for updates!</p>
      <button className={btnPrimary + " mt-6"}>Get Notified</button>
    </div>
  );
}

function UserCardRow({
  user,
  selected,
  onSelect,
  onManage,
  checked,
  onCheck
}: {
  user: UserRecord;
  selected: boolean;
  onSelect: () => void;
  onManage: () => void;
  checked: boolean;
  onCheck: (val: boolean) => void;
}) {
  const usagePercent = Math.min(100, user.plan_limit_bytes > 0 ? (user.used_bytes / user.plan_limit_bytes) * 100 : 0);
  const expired = isUserExpired(user.expire_at);
  const status = getUserStatus(user);
  const statusColor = status === 'Active' ? 'bg-emerald-500' : 'bg-rose-500';

  return (
    <div
      onClick={onSelect}
      className={`group relative flex cursor-pointer flex-col gap-3 rounded-xl border p-4 transition-all hover:shadow-md ${
        selected
          ? 'border-brand-500 bg-brand-50/30 ring-1 ring-brand-500 dark:bg-brand-500/5'
          : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700'
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => {
              e.stopPropagation();
              onCheck(e.target.checked);
            }}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500 dark:border-slate-700 dark:bg-slate-800"
          />
          <div className="min-w-0">
            <h5 className="truncate text-sm font-semibold text-slate-900 dark:text-white">{user.username}</h5>
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
              <span>{status}</span>
              <span>•</span>
              <span>ID: {user.owner_id || 'N/A'}</span>
            </div>
          </div>
        </div>
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => { e.stopPropagation(); onManage(); }}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          >
            <Icon name="fa-solid fa-ellipsis-vertical" />
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-slate-500">Usage</span>
          <span className="font-medium text-slate-700 dark:text-slate-300">
            {formatBytes(user.used_bytes)} / {user.plan_limit_bytes > 0 ? formatBytes(user.plan_limit_bytes) : '∞'}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className={`h-full transition-all duration-500 ${usagePercent > 90 ? 'bg-rose-500' : usagePercent > 70 ? 'bg-amber-500' : 'bg-brand-500'}`}
            style={{ width: `${usagePercent}%` }}
          />
        </div>
      </div>

      <div className="flex items-center justify-between text-[10px]">
        <div className="flex items-center gap-1 text-slate-500">
          <Icon name="fa-regular fa-calendar" />
          <span>Expires: {user.expire_at ? parseDate(user.expire_at) : 'Never'}</span>
        </div>
        {expired && (
          <span className="rounded bg-rose-50 px-1.5 py-0.5 font-bold uppercase text-rose-600 dark:bg-rose-500/10">Expired</span>
        )}
      </div>
    </div>
  );
}

function UserDetailsDrawer({
  user,
  onClose,
  onAction,
  busy,
  services,
  subInfo,
  onLoadSub
}: {
  user: UserRecord | null;
  onClose: () => void;
  onAction: (payload: any) => void;
  busy: boolean;
  services: ServiceRecord[];
  subInfo: SubscriptionResponse | null;
  onLoadSub: () => void;
}) {
  const [formLimit, setFormLimit] = useState('');
  const [formRenewDays, setFormRenewDays] = useState('');
  const [formServiceId, setFormServiceId] = useState('');

  useEffect(() => {
    if (user) {
      setFormLimit('');
      setFormRenewDays('');
      setFormServiceId(user.service_id ? String(user.service_id) : '');
    }
  }, [user]);

  if (!user) return null;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 w-full md:w-96">
      <div className="flex items-center justify-between border-b border-slate-200 p-4 dark:border-slate-800">
        <h3 className="text-lg font-bold text-slate-900 dark:text-white">User Details</h3>
        <button onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
          <Icon name="fa-solid fa-xmark" className="text-xl" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div className="flex items-center gap-4">
          <div className="h-16 w-16 rounded-2xl bg-brand-500 flex items-center justify-center text-white text-2xl font-bold">
            {user.username.charAt(0).toUpperCase()}
          </div>
          <div>
            <h4 className="text-xl font-bold text-slate-900 dark:text-white">@{user.username}</h4>
            {(() => {
              const status = getUserStatus(user);
              const statusClass = status === 'Active' ? 'text-emerald-500 font-semibold' : 'text-rose-500 font-semibold';
              return <p className="text-sm text-slate-500">Status: <span className={statusClass}>{status}</span></p>;
            })()}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <button
            disabled={busy}
            onClick={() => onAction({ disabled: !user.disabled })}
            className={user.disabled ? btnPrimary : btnSecondary}
          >
            <Icon name={user.disabled ? 'fa-solid fa-check' : 'fa-solid fa-ban'} />
            {user.disabled ? 'Enable' : 'Disable'}
          </button>
          <button
            disabled={busy}
            onClick={() => confirm('Are you sure?') && onAction({ delete: true })}
            className={btnSecondary + " text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-950/20"}
          >
            <Icon name="fa-solid fa-trash-can" />
            Delete
          </button>
        </div>

        <div className="space-y-4">
          <h5 className="text-sm font-semibold text-slate-900 dark:text-white border-b border-slate-100 pb-2 dark:border-slate-800">Quotas & Settings</h5>

          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-500">Update Limit (GB)</label>
              <div className="flex gap-2">
                <input className={inputClass} value={formLimit} onChange={e => setFormLimit(e.target.value)} placeholder="e.g. 50" />
                <button
                  disabled={busy || !formLimit}
                  onClick={() => onAction({ limit_bytes: Math.round(Number(formLimit) * 1024 * 1024 * 1024) })}
                  className={btnPrimary}
                >Apply</button>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-500">Renew Subscription (Days)</label>
              <div className="flex gap-2">
                <input className={inputClass} value={formRenewDays} onChange={e => setFormRenewDays(e.target.value)} placeholder="e.g. 30" />
                <button
                   disabled={busy || !formRenewDays}
                   onClick={() => onAction({ renew_days: Number(formRenewDays) })}
                   className={btnPrimary}
                >Renew</button>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-500">Assigned Service</label>
              <div className="flex gap-2">
                <select className={inputClass} value={formServiceId} onChange={e => setFormServiceId(e.target.value)}>
                  <option value="">No Service</option>
                  {services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                <button
                  disabled={busy || formServiceId === (user.service_id ? String(user.service_id) : '')}
                  onClick={() => onAction({ service_id: formServiceId ? Number(formServiceId) : null })}
                  className={btnPrimary}
                >Assign</button>
              </div>
            </div>

            <button
              disabled={busy}
              onClick={() => onAction({ reset_used: true })}
              className={btnSecondary + " w-full"}
            >
              <Icon name="fa-solid fa-rotate-left" />
              Reset Data Usage
            </button>
          </div>
        </div>

        <div className="space-y-4 pt-2">
          <h5 className="text-sm font-semibold text-slate-900 dark:text-white border-b border-slate-100 pb-2 dark:border-slate-800">Access Info</h5>
          <button
            disabled={busy}
            onClick={onLoadSub}
            className={btnSecondary + " w-full"}
          >
            <Icon name="fa-solid fa-qrcode" />
            {subInfo ? 'Refresh QR Codes' : 'Show Subscription Info'}
          </button>

          {subInfo && (
            <div className="space-y-4">
              {subInfo.urls.map((url, idx) => (
                <div key={idx} className="space-y-2 rounded-lg border border-slate-100 p-3 dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase text-slate-400">Link #{idx+1}</span>
                    <button
                      onClick={() => { navigator.clipboard.writeText(url); alert('Copied!'); }}
                      className="text-xs text-brand-600 hover:underline"
                    >Copy</button>
                  </div>
                  <p className="break-all text-[10px] text-slate-500">{url}</p>
                  <img src={subInfo.qr_data_uris[idx]} className="mx-auto h-40 w-40 rounded-lg bg-white p-2" alt="QR Code" />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {[1,2,3,4,5].map(i => (
        <div key={i} className="animate-pulse rounded-xl border border-slate-100 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-800/50">
          <div className="flex gap-4">
            <div className="h-10 w-10 rounded-lg bg-slate-200 dark:bg-slate-700" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-1/4 rounded bg-slate-200 dark:bg-slate-700" />
              <div className="h-3 w-1/2 rounded bg-slate-200 dark:bg-slate-700" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function HomePage() {
  const [showPanelUsageModal, setShowPanelUsageModal] = useState(false);
  const [panelUsageLoading, setPanelUsageLoading] = useState(false);
  const [panelUsage, setPanelUsage] = useState<PanelUsageRecord[]>([]);
  const [totalUsage, setTotalUsage] = useState(0);

  const fetchPanelUsage = useCallback(async () => {
    try {
      setPanelUsageLoading(true);
      const res = await fetch('/api/v1/web/usage-by-panel', { credentials: 'same-origin' });
      if (res.status === 401) { window.location.replace('/web/login'); return; }
      if (!res.ok) return;
      const data = await res.json() as PanelUsageResponse;
      setPanelUsage(Array.isArray(data.panels) ? data.panels : []);
      if (typeof data.total_used_bytes === 'number') setTotalUsage(data.total_used_bytes);
    } finally {
      setPanelUsageLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPanelUsage();
  }, [fetchPanelUsage]);

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6">
      <div className="mb-4">
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Dashboard Home</h2>
        <p className="text-sm text-slate-500">Overview and global usage insights.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <InsightCard
          label="Lifetime Panel Usage"
          value={formatBytes(totalUsage)}
          icon="fa-solid fa-database"
          onClick={() => {
            setShowPanelUsageModal(true);
            fetchPanelUsage();
          }}
        />
      </div>

      <PanelUsageModal
        open={showPanelUsageModal}
        onClose={() => setShowPanelUsageModal(false)}
        loading={panelUsageLoading}
        totalUsedBytes={totalUsage}
        panels={panelUsage}
      />
    </div>
  );
}

function UsersPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'active' | 'disabled' | 'expiring' | 'usage'>('all');
  const [sortBy, setSortBy] = useState<'username' | 'usage' | 'expiry'>('username');
  const [selectedUser, setSelectedUser] = useState<UserRecord | null>(null);
  const [services, setServices] = useState<ServiceRecord[]>([]);
  const [subInfo, setSubInfo] = useState<SubscriptionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [checkedUsers, setCheckedUsers] = useState<Set<string>>(new Set());
  const [showCreateModal, setShowCreateModal] = useState(false);

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/v1/web/users?limit=200', { credentials: 'same-origin' });
      if (res.status === 401) { window.location.replace('/web/login'); return; }
      const data = await res.json() as UsersResponse;
      setUsers(data.users || []);
    } catch {
      setError('Failed to load users.');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchServices = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/web/services', { credentials: 'same-origin' });
      if (res.ok) {
        const data = await res.json();
        setServices(Array.isArray(data) ? data : []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchUsers();
    fetchServices();
  }, [fetchUsers, fetchServices]);

  const filteredUsers = useMemo(() => {
    let result = users.filter(u => u.username.toLowerCase().includes(search.toLowerCase()));
    if (filter === 'active') result = result.filter(u => getUserStatus(u) === 'Active');
    if (filter === 'disabled') result = result.filter(u => getUserStatus(u) !== 'Active');
    if (filter === 'usage') result = result.filter(u => u.plan_limit_bytes > 0 && (u.used_bytes / u.plan_limit_bytes) > 0.8);
    if (filter === 'expiring') {
      result = result.filter(u => isUserExpiringSoon(u.expire_at));
    }

    result.sort((a, b) => {
      if (sortBy === 'username') return a.username.localeCompare(b.username);
      if (sortBy === 'usage') return b.used_bytes - a.used_bytes;
      if (sortBy === 'expiry') {
        if (!a.expire_at) return 1;
        if (!b.expire_at) return -1;
        return new Date(a.expire_at).getTime() - new Date(b.expire_at).getTime();
      }
      return 0;
    });

    return result;
  }, [users, search, filter, sortBy]);

  const stats = useMemo(() => {
    const active = users.filter(u => getUserStatus(u) === 'Active').length;
    const expiring = users.filter(u => isUserExpiringSoon(u.expire_at)).length;
    const highUsage = users.filter(u => u.plan_limit_bytes > 0 && (u.used_bytes / u.plan_limit_bytes) > 0.8).length;
    return { total: users.length, active, disabled: users.length - active, expiring, highUsage };
  }, [users]);

  const handleAction = async (payload: any) => {
    if (!selectedUser) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}`, {
        method: payload.delete ? 'DELETE' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: payload.delete ? undefined : JSON.stringify(payload),
      });
      if (res.ok) {
        if (payload.delete) {
          setUsers(prev => prev.filter(u => u.username !== selectedUser.username));
          setSelectedUser(null);
        } else {
          const updated = await res.json();
          setUsers(prev => prev.map(u => u.username === updated.username ? updated : u));
          setSelectedUser(updated);
        }
      }
    } catch {
      alert('Action failed');
    } finally {
      setBusy(false);
    }
  };

  const loadSub = async () => {
    if (!selectedUser) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/web/users/${encodeURIComponent(selectedUser.username)}/subscription`, { credentials: 'same-origin' });
      if (res.ok) setSubInfo(await res.json());
    } catch {
      alert('Failed to load subscription info');
    } finally {
      setBusy(false);
    }
  };

  const toggleCheck = (username: string, val: boolean) => {
    const next = new Set(checkedUsers);
    if (val) next.add(username); else next.delete(username);
    setCheckedUsers(next);
  };

  const toggleAll = (val: boolean) => {
    if (val) setCheckedUsers(new Set(filteredUsers.map(u => u.username)));
    else setCheckedUsers(new Set());
  };

  return (
    <div className="flex flex-col md:h-full md:flex-row md:overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col md:overflow-hidden">
        {/* Workspace Header */}
        <div className="flex flex-col gap-4 border-b border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Users Workspace</h2>
            <p className="text-sm text-slate-500">Manage and monitor all your local users and their subscriptions.</p>
          </div>
          <button onClick={() => setShowCreateModal(true)} className={btnPrimary}>
            <Icon name="fa-solid fa-plus" />
            Create User
          </button>
        </div>

        {/* Insights */}
        <div className="grid grid-cols-2 gap-4 border-b border-slate-200 bg-slate-50/30 p-4 dark:border-slate-800 dark:bg-slate-900/50 md:grid-cols-3 lg:grid-cols-5">
          <InsightCard label="Total Users" value={stats.total} icon="fa-solid fa-users" />
          <InsightCard label="Active" value={stats.active} icon="fa-solid fa-check-circle" />
          <InsightCard label="Disabled" value={stats.disabled} icon="fa-solid fa-ban" />
          <InsightCard label="Expiring Soon" value={stats.expiring} icon="fa-solid fa-clock" trend="Urgent" trendUp={false} />
          <InsightCard label="High Usage" value={stats.highUsage} icon="fa-solid fa-chart-line" className="col-span-2 md:col-span-1" />
        </div>

        {/* Filters Bar */}
        {error && (
          <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-600 dark:border-rose-800/40 dark:bg-rose-500/10 dark:text-rose-300">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-3 border-b border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Icon name="fa-solid fa-magnifying-glass" className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              className={inputClass + " pl-10"}
              placeholder="Filter by username..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <label className="text-xs font-semibold text-slate-400 uppercase">Sort:</label>
            <select
              className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
              value={sortBy}
              onChange={e => setSortBy(e.target.value as any)}
            >
              <option value="username">Name</option>
              <option value="usage">Usage</option>
              <option value="expiry">Expiry</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { id: 'all', label: 'All' },
              { id: 'active', label: 'Active' },
              { id: 'disabled', label: 'Disabled' },
              { id: 'usage', label: 'High Usage' },
              { id: 'expiring', label: 'Expiring' },
            ].map((f, idx, arr) => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id as any)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${idx === arr.length - 1 ? 'w-full text-center sm:w-auto' : ''} ${
                  filter === f.id
                    ? 'bg-brand-600 text-white dark:bg-brand-500'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                }`}
              >{f.label}</button>
            ))}
          </div>
        </div>

        {/* User List Area */}
        <div className="flex-1 overflow-visible bg-slate-50/50 p-4 dark:bg-black/20 md:overflow-y-auto">
          {checkedUsers.size > 0 && (
            <div className="mb-4 flex items-center justify-between rounded-lg bg-brand-600 p-2 text-white shadow-lg dark:bg-brand-500">
              <span className="text-sm font-bold ml-2">{checkedUsers.size} users selected</span>
              <div className="flex gap-2">
                <button className="rounded bg-white/20 px-3 py-1 text-xs hover:bg-white/30">Disable All</button>
                <button className="rounded bg-white/20 px-3 py-1 text-xs hover:bg-white/30">Extend (30d)</button>
                <button className="rounded bg-rose-500 px-3 py-1 text-xs font-bold shadow-sm" onClick={() => setCheckedUsers(new Set())}>Cancel</button>
              </div>
            </div>
          )}

          <div className="mb-4 flex items-center gap-2">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 text-brand-600"
              onChange={e => toggleAll(e.target.checked)}
              checked={filteredUsers.length > 0 && checkedUsers.size === filteredUsers.length}
            />
            <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Select All Visible</span>
          </div>

          {loading ? <LoadingSkeleton /> : (
            <div className="grid gap-4 lg:grid-cols-2">
              {filteredUsers.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-center bg-white dark:bg-slate-900 rounded-2xl border border-dashed border-slate-200 dark:border-slate-800">
                  <Icon name="fa-solid fa-user-slash" className="text-4xl text-slate-300 mb-4" />
                  <p className="text-slate-500">No users found matching your filters.</p>
                </div>
              ) : filteredUsers.map(user => (
                <UserCardRow
                  key={user.username}
                  user={user}
                  selected={selectedUser?.username === user.username}
                  onSelect={() => { setSelectedUser(user); setSubInfo(null); }}
                  onManage={() => { setSelectedUser(user); setSubInfo(null); }}
                  checked={checkedUsers.has(user.username)}
                  onCheck={v => toggleCheck(user.username, v)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <UserDetailsDrawer
        user={selectedUser}
        onClose={() => setSelectedUser(null)}
        onAction={handleAction}
        busy={busy}
        services={services}
        subInfo={subInfo}
        onLoadSub={loadSub}
      />

      {showCreateModal && (
        <CreateUserModal
          services={services}
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => { setShowCreateModal(false); fetchUsers(); }}
        />
      )}
    </div>
  );
}

function CreateUserModal({ services, onClose, onSuccess }: { services: ServiceRecord[]; onClose: () => void; onSuccess: () => void }) {
  const [username, setUsername] = useState('');
  const [limitGb, setLimitGb] = useState('');
  const [days, setDays] = useState('');
  const [serviceId, setServiceId] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await fetch('/api/v1/web/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          username,
          limit_bytes: limitGb ? Math.round(Number(limitGb) * 1024 * 1024 * 1024) : 0,
          duration_days: days ? Number(days) : 0,
          service_id: serviceId ? Number(serviceId) : null,
        }),
      });
      if (res.ok) onSuccess(); else alert('Failed to create user');
    } catch {
      alert('Error occurred');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className={cardClass + " w-full max-w-md p-6 shadow-2xl"} onClick={e => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-xl font-bold text-slate-900 dark:text-white">Create New User</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
            <Icon name="fa-solid fa-xmark" className="text-xl" />
          </button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Username</label>
            <input required className={inputClass} value={username} onChange={e => setUsername(e.target.value)} placeholder="e.g. john_doe" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Traffic Limit (GB)</label>
              <input className={inputClass} value={limitGb} onChange={e => setLimitGb(e.target.value)} placeholder="e.g. 50" />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Duration (Days)</label>
              <input className={inputClass} value={days} onChange={e => setDays(e.target.value)} placeholder="e.g. 30" />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Assign Service</label>
            <select className={inputClass} value={serviceId} onChange={e => setServiceId(e.target.value)}>
              <option value="">No Service</option>
              {services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className={btnSecondary + " flex-1"}>Cancel</button>
            <button type="submit" disabled={busy} className={btnPrimary + " flex-1"}>{busy ? 'Creating...' : 'Create User'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function LoginPage({ onLogin }: { onLogin: () => void }) {
  const { theme, toggleTheme } = useTheme();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

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

      if (res.ok) { onLogin(); return; }
      setError(res.status === 429 ? 'Too many attempts.' : 'Invalid credentials.');
    } catch {
      setError('Unable to login.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <div className={cardClass + " w-full max-w-md p-8 shadow-2xl"}>
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-600 text-white shadow-lg dark:bg-brand-500">
            <Icon name="fa-solid fa-shield-halved" className="text-3xl" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">Valhalla Admin</h1>
          <p className="mt-2 text-sm text-slate-500">Sign in to manage your aggregator console.</p>
        </div>

        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-1">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Username</label>
            <input required className={inputClass} value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Password</label>
            <input required type="password" className={inputClass} value={password} onChange={e => setPassword(e.target.value)} />
          </div>
          <button disabled={busy} type="submit" className={btnPrimary + " w-full py-3 text-base shadow-lg"}>
            {busy ? 'Signing in...' : 'Sign In'}
          </button>
          {error && <p className="text-center text-sm font-medium text-rose-500">{error}</p>}
        </form>

        <div className="mt-8 flex justify-center">
           <button onClick={toggleTheme} className="text-xs text-slate-400 hover:text-slate-600">
             {theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
           </button>
        </div>
      </div>
    </main>
  );
}

function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const res = await fetch('/api/v1/web/me', { credentials: 'same-origin' });
        setIsLoggedIn(res.ok);
      } catch {
        setIsLoggedIn(false);
      }
    };
    checkAuth();
  }, []);

  const navigate = (newPath: string) => {
    window.history.pushState({}, '', newPath);
    setPath(newPath);
  };

  const handleLogout = async () => {
    await fetch('/api/v1/web/logout', { method: 'POST', credentials: 'same-origin' });
    window.location.replace('/web/login');
  };

  if (isLoggedIn === null) return <div className="flex h-screen items-center justify-center"><div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-500 border-t-transparent" /></div>;
  if (!isLoggedIn) return <LoginPage onLogin={() => setIsLoggedIn(true)} />;

  const renderContent = () => {
    switch (path) {
      case '/web/users': return <UsersPage />;
      case '/web/home': return <HomePage />;
      case '/web/services': return <ComingSoon title="Services Management" />;
      case '/web/nodes': return <ComingSoon title="Nodes Monitoring" />;
      case '/web/hosts': return <ComingSoon title="Hosts Configuration" />;
      case '/web/admins': return <ComingSoon title="Admin Accounts" />;
      case '/web/settings': return <ComingSoon title="System Settings" />;
      default: return <UsersPage />;
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-50 transition-colors dark:bg-slate-950 md:h-screen">
      <Sidebar
        collapsed={sidebarCollapsed}
        mobileOpen={mobileSidebarOpen}
        setMobileOpen={setMobileSidebarOpen}
        currentPath={path}
        onNavigate={navigate}
      />

      <div className={`flex flex-1 flex-col overflow-visible transition-all duration-300 md:overflow-hidden ${sidebarCollapsed ? 'md:pl-16' : 'md:pl-64'}`}>
        <TopBar
          onToggleSidebar={() => {
            if (window.innerWidth < 768) setMobileSidebarOpen(true);
            else setSidebarCollapsed(!sidebarCollapsed);
          }}
          onToggleTheme={toggleTheme}
          theme={theme}
          onLogout={handleLogout}
        />

        <main className="flex-1 overflow-visible md:overflow-hidden">
          {renderContent()}
        </main>
      </div>
    </div>
  );
}

const rootNode = document.getElementById('root');
if (rootNode) {
  ReactDOM.createRoot(rootNode).render(<App />);
}
