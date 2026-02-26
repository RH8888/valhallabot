const { Fragment } = React;

type LayoutShellProps = {
  title: string;
  subtitle: string;
  primaryActionLabel: string;
  onPrimaryAction: () => void;
  onLogout: () => void;
  children: React.ReactNode;
};

export function LayoutShell(props: LayoutShellProps) {
  const { title, subtitle, primaryActionLabel, onPrimaryAction, onLogout, children } = props;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto flex min-h-screen w-full max-w-[1440px] flex-col lg:flex-row">
        <aside className="border-b border-slate-200 bg-white px-4 py-4 lg:w-64 lg:border-b-0 lg:border-r lg:px-6 lg:py-6">
          <div className="flex items-center justify-between lg:block">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">Valhalla Admin</p>
              <h1 className="mt-2 text-xl font-semibold text-slate-900">Control Panel</h1>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Logout
            </button>
          </div>
          <nav className="mt-6 flex gap-2 lg:flex-col">
            <a
              href="/web/users"
              className="rounded-lg bg-indigo-50 px-4 py-3 text-sm font-medium text-indigo-700"
              aria-current="page"
            >
              Manage users
            </a>
          </nav>
        </aside>

        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
          <header className="mb-6 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between sm:p-6">
            <div>
              <h2 className="text-2xl font-semibold text-slate-900">{title}</h2>
              <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
            </div>
            <button
              type="button"
              onClick={onPrimaryAction}
              className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500"
            >
              {primaryActionLabel}
            </button>
          </header>
          <Fragment>{children}</Fragment>
        </main>
      </div>
    </div>
  );
}
