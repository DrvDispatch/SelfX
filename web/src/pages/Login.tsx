import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ArrowDown, ArrowRight, FileAudio, FileText, Loader2, Workflow } from "lucide-react";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import Brand from "../components/Brand";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (user) return <Navigate to={from} replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const field =
    "w-full rounded-lg border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg transition-colors focus:border-primary";

  return (
    <div className="grid min-h-dvh bg-bg md:grid-cols-[minmax(0,0.88fr)_minmax(0,1fr)]">
      <main className="flex items-center justify-center px-5 py-9 sm:px-8">
        <div className="w-full max-w-[26rem]">
          <div className="mb-8"><Brand large /></div>
          <form onSubmit={(e) => void onSubmit(e)} className="rounded-2xl border border-line bg-surface px-5 py-6 shadow-[var(--shadow-card)] sm:p-8">
            <h1 className="text-3xl leading-tight font-bold tracking-[-0.05em] text-fg">Sign in</h1>
            <p className="mt-1.5 mb-6 text-sm leading-relaxed text-muted">Use your SelfX account on this server.</p>
            <label htmlFor="username" className="mb-1.5 block text-sm font-semibold text-fg">Username</label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={`mb-4 ${field}`}
            />
            <label htmlFor="password" className="mb-1.5 block text-sm font-semibold text-fg">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={`mb-5 ${field}`}
            />
            {error && <p role="alert" className="mb-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-danger">{error}</p>}
            <button type="submit" disabled={busy}
              className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-60">
              {busy ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <ArrowRight aria-hidden="true" className="size-4" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
      <aside className="workspace-plan-panel m-4 ml-0 hidden justify-center rounded-3xl border border-ink-panel-line px-7 py-8 md:flex lg:m-5 lg:ml-0 lg:px-11">
        <div className="flex w-full max-w-lg flex-col justify-center">
          <h2 className="max-w-sm text-[clamp(2rem,4vw,4rem)] leading-[1.02] font-bold tracking-[-0.06em]">Work with files on your server.</h2>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-ink-panel-muted">Convert, organize, and transcribe files. Save frequent steps as recipes you can run again.</p>
          <div className="mt-8 max-w-sm">
            <div className="flex items-center gap-3 rounded-xl border border-ink-panel-line bg-ink-panel px-4 py-3">
              <FileAudio aria-hidden="true" className="size-5 shrink-0 text-ink-panel-accent" />
              <p className="text-sm font-medium">Recording</p>
            </div>
            <ArrowDown aria-hidden="true" className="my-1 ml-[1.125rem] size-4 text-ink-panel-muted" />
            <div className="flex items-center gap-3 rounded-xl border border-ink-panel-line bg-ink-panel px-4 py-3">
              <Workflow aria-hidden="true" className="size-5 shrink-0 text-ink-panel-accent" />
              <p className="text-sm font-medium">Transcribe</p>
            </div>
            <ArrowDown aria-hidden="true" className="my-1 ml-[1.125rem] size-4 text-ink-panel-muted" />
            <div className="flex items-center gap-3 rounded-xl border border-ink-panel-line bg-ink-panel px-4 py-3">
              <FileText aria-hidden="true" className="size-5 shrink-0 text-ink-panel-accent" />
              <p className="text-sm font-medium">Transcript and captions</p>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
