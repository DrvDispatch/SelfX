import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { HardDrive, Layers, ListChecks, Users } from "lucide-react";
import {
  ApiError,
  adminCreateUser,
  adminDeleteUser,
  adminListUsers,
  adminStats,
  adminUpdateUser,
} from "../api";
import { useAuth } from "../auth";
import { formatBytes } from "../format";
import type { AdminStats, User } from "../types";

function StatCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
      <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-faint">
        {icon}
        {label}
      </div>
      <div className="text-lg font-semibold text-fg">{value}</div>
    </div>
  );
}

// Map a job/user status to a semantic color + whether to use a soft tinted pill.
const STATUS_STYLE: Record<string, { color: string; tint: boolean }> = {
  done: { color: "var(--color-ok)", tint: true },
  error: { color: "var(--color-danger)", tint: true },
  running: { color: "var(--color-primary)", tint: true },
  queued: { color: "var(--color-muted)", tint: false },
  canceled: { color: "var(--color-faint)", tint: false },
};

function StatusBadge({ status, count }: { status: string; count?: ReactNode }) {
  const s = STATUS_STYLE[status] ?? { color: "var(--color-muted)", tint: false };
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
      style={{
        color: s.color,
        background: s.tint
          ? `color-mix(in srgb, ${s.color} 14%, transparent)`
          : "var(--color-surface-2)",
      }}
    >
      {status}
      {count !== undefined && (
        <span className="font-semibold" style={{ color: s.color }}>
          {count}
        </span>
      )}
    </span>
  );
}

export default function Admin() {
  const { user: currentUser } = useAuth();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, u] = await Promise.all([adminStats(), adminListUsers()]);
      setStats(s);
      setUsers(u);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Failed to load admin data");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Action failed");
    }
  };

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (creating || !newUsername.trim() || !newPassword) return;
    setCreating(true);
    await run(() => adminCreateUser(newUsername.trim(), newPassword, newIsAdmin));
    setCreating(false);
    setNewUsername("");
    setNewPassword("");
    setNewIsAdmin(false);
  };

  const resetPassword = (u: User) => {
    const pw = window.prompt(`New password for ${u.username}:`);
    if (!pw) return;
    void run(() => adminUpdateUser(u.id, { password: pw }));
  };

  const jobsByStatus = Object.entries(stats?.jobs_by_status ?? {});

  const field =
    "w-full rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg outline-none transition-colors placeholder:text-faint focus:border-primary";
  const rowBtn =
    "rounded-full bg-surface-2 px-3 py-1.5 text-xs font-medium transition-colors hover:bg-line disabled:opacity-40";

  return (
    <div className="mx-auto max-w-5xl p-6">
      <h1 className="mb-6 text-2xl font-bold tracking-tight text-fg">Admin</h1>

      {error && (
        <p className="mb-4 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={<Users className="h-3.5 w-3.5" />}
          label="Users"
          value={stats ? String(stats.users) : "…"}
        />
        <StatCard
          icon={<ListChecks className="h-3.5 w-3.5" />}
          label="Jobs total"
          value={stats ? String(stats.jobs_total) : "…"}
        />
        <StatCard
          icon={<HardDrive className="h-3.5 w-3.5" />}
          label="Disk used"
          value={stats ? formatBytes(stats.disk_used_bytes) : "…"}
        />
        <StatCard
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Queue depth"
          value={
            stats
              ? `default ${stats.queue_depth.default} · heavy ${stats.queue_depth.heavy}`
              : "…"
          }
        />
      </div>

      {jobsByStatus.length > 0 && (
        <div className="mb-8 flex flex-wrap gap-2">
          {jobsByStatus.map(([status, count]) => (
            <StatusBadge key={status} status={status} count={count} />
          ))}
        </div>
      )}

      <section className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-fg">Users</h2>
        <div className="overflow-x-auto rounded-2xl border border-line bg-surface shadow-[var(--shadow-card)]">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="border-b border-line bg-surface-2 text-xs uppercase tracking-wide text-faint">
                <th className="px-4 py-3 font-medium">Username</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = u.id === currentUser?.id;
                return (
                  <tr key={u.id} className="border-b border-line">
                    <td className="px-4 py-3 text-fg">
                      {u.username}
                      {isSelf && (
                        <span className="ml-2 text-xs text-faint">(you)</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted">
                      {u.is_admin ? "admin" : "user"}
                    </td>
                    <td className="px-4 py-3">
                      {u.disabled ? (
                        <span
                          className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium text-danger"
                          style={{ background: "color-mix(in srgb, var(--color-danger) 14%, transparent)" }}
                        >
                          disabled
                        </span>
                      ) : (
                        <span
                          className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium text-ok"
                          style={{ background: "color-mix(in srgb, var(--color-ok) 14%, transparent)" }}
                        >
                          active
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => resetPassword(u)}
                          className={`${rowBtn} text-fg`}
                        >
                          Reset password
                        </button>
                        <button
                          type="button"
                          disabled={isSelf}
                          onClick={() =>
                            void run(() =>
                              adminUpdateUser(u.id, { is_admin: !u.is_admin }),
                            )
                          }
                          className={`${rowBtn} text-fg`}
                        >
                          {u.is_admin ? "Revoke admin" : "Make admin"}
                        </button>
                        <button
                          type="button"
                          disabled={isSelf}
                          onClick={() =>
                            void run(() =>
                              adminUpdateUser(u.id, { disabled: !u.disabled }),
                            )
                          }
                          className={`${rowBtn} text-warn`}
                        >
                          {u.disabled ? "Enable" : "Disable"}
                        </button>
                        <button
                          type="button"
                          disabled={isSelf}
                          onClick={() => {
                            if (window.confirm(`Delete user ${u.username}?`)) {
                              void run(() => adminDeleteUser(u.id));
                            }
                          }}
                          className={`${rowBtn} text-danger`}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-fg">
          Create user
        </h2>
        <form
          onSubmit={(e) => void onCreate(e)}
          className="flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-surface p-4 shadow-[var(--shadow-card)]"
        >
          <div>
            <label htmlFor="new-username" className="mb-1.5 block text-sm font-medium text-fg">
              Username
            </label>
            <input
              id="new-username"
              type="text"
              required
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              className={field}
            />
          </div>
          <div>
            <label htmlFor="new-password" className="mb-1.5 block text-sm font-medium text-fg">
              Password
            </label>
            <input
              id="new-password"
              type="password"
              required
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className={field}
            />
          </div>
          <label className="flex cursor-pointer items-center gap-2 pb-2.5 text-sm font-medium text-fg">
            <input
              type="checkbox"
              checked={newIsAdmin}
              onChange={(e) => setNewIsAdmin(e.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            Admin
          </label>
          <button
            type="submit"
            disabled={creating}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {creating ? "Creating…" : "Create"}
          </button>
        </form>
      </section>
    </div>
  );
}
