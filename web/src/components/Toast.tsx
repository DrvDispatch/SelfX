import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";

export type ToastKind = "success" | "error" | "info" | "loading";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  /** ms before auto-dismiss; 0 = sticky (caller dismisses). */
  duration: number;
}

interface ToastApi {
  success: (message: string, duration?: number) => number;
  error: (message: string, duration?: number) => number;
  info: (message: string, duration?: number) => number;
  loading: (message: string) => number;
  dismiss: (id: number) => void;
  /** Update an existing toast (e.g. a loading toast → success). */
  update: (id: number, patch: Partial<Omit<Toast, "id">>) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

const META: Record<ToastKind, { Icon: typeof Info; cls: string }> = {
  success: { Icon: CheckCircle2, cls: "text-ok" },
  error: { Icon: XCircle, cls: "text-danger" },
  info: { Icon: Info, cls: "text-primary" },
  loading: { Icon: Loader2, cls: "text-primary" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
    const tm = timers.current.get(id);
    if (tm) {
      clearTimeout(tm);
      timers.current.delete(id);
    }
  }, []);

  const schedule = useCallback((id: number, duration: number) => {
    const existing = timers.current.get(id);
    if (existing) clearTimeout(existing);
    if (duration > 0) {
      timers.current.set(id, setTimeout(() => dismiss(id), duration));
    }
  }, [dismiss]);

  const push = useCallback((kind: ToastKind, message: string, duration: number) => {
    const id = ++idRef.current;
    setToasts((t) => [...t.slice(-4), { id, kind, message, duration }]);
    schedule(id, duration);
    return id;
  }, [schedule]);

  const update = useCallback((id: number, patch: Partial<Omit<Toast, "id">>) => {
    setToasts((t) => t.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    if (patch.duration !== undefined) schedule(id, patch.duration);
  }, [schedule]);

  const api = useMemo<ToastApi>(() => ({
    success: (m, d = 3500) => push("success", m, d),
    error: (m, d = 6000) => push("error", m, d),
    info: (m, d = 4000) => push("info", m, d),
    loading: (m) => push("loading", m, 0),
    dismiss,
    update,
  }), [push, dismiss, update]);

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-[calc(4.4rem+env(safe-area-inset-bottom))] z-[100] mx-auto flex max-w-sm flex-col gap-2 lg:inset-x-auto lg:right-5 lg:bottom-5 lg:mx-0 lg:w-sm">
        {toasts.map((t) => {
          const { Icon, cls } = META[t.kind];
          return (
            <div
              key={t.id}
              role="status"
              className="animate-in pointer-events-auto flex items-start gap-2.5 rounded-xl border border-line bg-surface px-3.5 py-3 shadow-[var(--shadow-pop)]"
            >
              <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${cls} ${t.kind === "loading" ? "animate-spin" : ""}`} />
              <p className="min-w-0 flex-1 text-sm leading-snug text-fg">{t.message}</p>
              {t.kind !== "loading" && (
                <button
                  onClick={() => dismiss(t.id)}
                  aria-label="Dismiss"
                  className="-mr-1 -mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md text-faint transition-colors hover:bg-surface-2 hover:text-fg"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

/** Marker icons re-exported for callers that want the alert glyph. */
export const ToastIcons = { AlertTriangle };
