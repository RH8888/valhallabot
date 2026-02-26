import * as Dialog from 'https://esm.sh/@radix-ui/react-dialog@1.1.2?dev';
import type { ServiceRecord, UserFormValues } from '../types.ts';

type UserModalProps = {
  open: boolean;
  mode: 'create' | 'edit';
  title: string;
  services: ServiceRecord[];
  values: UserFormValues;
  saving: boolean;
  error: string;
  onOpenChange: (open: boolean) => void;
  onChange: (next: UserFormValues) => void;
  onSubmit: (event: React.FormEvent) => void;
};

export function UserModal(props: UserModalProps) {
  const { open, mode, title, services, values, saving, error, onOpenChange, onChange, onSubmit } = props;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[94vw] max-w-[680px] -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-5 shadow-2xl sm:p-6">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="text-xl font-semibold text-slate-900">{title}</Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-slate-500">
                {mode === 'create' ? 'Create a new user account with quota and duration.' : 'Edit user settings and renew limits.'}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button type="button" className="rounded-md border border-slate-300 px-2 py-1 text-sm">Close</button>
            </Dialog.Close>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            <label className="block text-sm font-medium text-slate-700">
              Username
              <input
                value={values.username}
                onChange={(event) => onChange({ ...values, username: event.target.value })}
                disabled={mode === 'edit'}
                required
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-100"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              Traffic limit (GB)
              <input
                value={values.limitGb}
                onChange={(event) => onChange({ ...values, limitGb: event.target.value })}
                placeholder="e.g. 50"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              Duration / renew days
              <input
                value={values.durationDays}
                onChange={(event) => onChange({ ...values, durationDays: event.target.value })}
                placeholder="e.g. 30"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              Service
              <select
                value={values.serviceId}
                onChange={(event) => onChange({ ...values, serviceId: event.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">No service</option>
                {services.map((service) => (
                  <option key={service.id} value={service.id}>{service.name} (#{service.id})</option>
                ))}
              </select>
            </label>

            {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}

            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <Dialog.Close asChild>
                <button type="button" className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium">Cancel</button>
              </Dialog.Close>
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving…' : mode === 'create' ? 'Create user' : 'Save changes'}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
