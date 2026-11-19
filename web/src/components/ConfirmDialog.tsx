import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface ConfirmOpts {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (opts: ConfirmOpts) => Promise<boolean>;

const Ctx = createContext<ConfirmFn | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useConfirm(): ConfirmFn {
  const c = useContext(Ctx);
  if (!c) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return c;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOpts | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const labelId = useId();
  const descriptionId = useId();

  const confirm = useCallback<ConfirmFn>((options) => new Promise((resolve) => {
    if (resolver.current) {
      resolve(false);
      return;
    }
    resolver.current = resolve;
    setOpts(options);
  }), []);

  const close = useCallback((value: boolean) => {
    dialogRef.current?.close();
    resolver.current?.(value);
    resolver.current = null;
    setOpts(null);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!opts || !dialog) return;
    dialog.showModal();
    cancelRef.current?.focus();
    return () => dialog.close();
  }, [opts]);

  return (
    <Ctx.Provider value={confirm}>
      {children}
      {opts && (
        <dialog
          ref={dialogRef}
          role="alertdialog"
          aria-labelledby={labelId}
          aria-describedby={opts.message ? descriptionId : undefined}
          onCancel={(event) => { event.preventDefault(); close(false); }}
          onClick={(event) => { if (event.target === event.currentTarget) close(false); }}
          className="m-auto w-[calc(100%-2rem)] max-w-sm rounded-2xl border border-line bg-surface p-0 text-fg shadow-[var(--shadow-pop)] backdrop:bg-black/50 backdrop:backdrop-blur-sm"
        >
          <div className="p-5">
            <div className="flex items-start gap-3">
              {opts.danger && (
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-danger/10">
                  <AlertTriangle aria-hidden="true" className="h-5 w-5 text-danger" />
                </span>
              )}
              <div className="min-w-0">
                <h2 id={labelId} className="text-base font-semibold text-fg">{opts.title}</h2>
                {opts.message && <p id={descriptionId} className="mt-1 text-sm text-muted">{opts.message}</p>}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={() => close(false)}
                className="rounded-xl bg-surface-2 px-4 py-2 text-sm font-medium text-fg transition-colors hover:bg-line"
              >
                {opts.cancelLabel || "Cancel"}
              </button>
              <button
                type="button"
                onClick={() => close(true)}
                className={`rounded-xl px-4 py-2 text-sm font-semibold text-primary-fg transition-opacity hover:opacity-90 ${
                  opts.danger ? "bg-danger" : "bg-primary"
                }`}
              >
                {opts.confirmLabel || "Confirm"}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </Ctx.Provider>
  );
}
