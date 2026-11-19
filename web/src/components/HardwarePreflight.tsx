import { useEffect, useState } from "react";
import { Cpu, RefreshCw } from "lucide-react";
import { getModelHardware, type ModelHardware } from "../api";
import { formatBytes } from "../format";

function size(bytes: number | null): string {
  return bytes === null ? "Unavailable" : formatBytes(bytes);
}

export default function HardwarePreflight({ onUseModel }: { onUseModel: (model: string) => void }) {
  const [hardware, setHardware] = useState<ModelHardware | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    getModelHardware(controller.signal)
      .then((snapshot) => {
        if (!controller.signal.aborted) setHardware(snapshot);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setFailed(true);
          setHardware(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt]);

  const recommendation = hardware?.recommendation;
  const recommendedModel = recommendation?.model;
  const gpu = hardware?.nvidia_gpus;

  return (
    <section aria-labelledby="hardware-title" className="mb-6 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Cpu aria-hidden="true" className="size-5 shrink-0 text-primary" />
          <h2 id="hardware-title" className="font-semibold text-fg">Hardware check</h2>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => setAttempt((previous) => previous + 1)}
          className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-line px-2.5 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50"
        >
          <RefreshCw aria-hidden="true" className="size-4" /> Refresh hardware
        </button>
      </div>

      {loading && <p role="status" className="mt-2 text-sm text-muted">Checking server resources…</p>}
      {failed && <p role="status" className="mt-2 text-sm text-muted">Could not read server resources. Refresh to try again.</p>}

      {hardware && (
        <>
          <p className="mt-2 text-sm text-muted">
            {hardware.scope === "api_container" ? "SelfX API container" : "SelfX API host"} · {hardware.os} · {hardware.architecture}
          </p>
          <p className="mt-1 text-xs text-muted">{hardware.scope_note}</p>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted">CPU capacity</dt>
              <dd className="font-medium text-fg">{hardware.effective_cpu_cores.toLocaleString(undefined, { maximumFractionDigits: 2 })} cores</dd>
            </div>
            <div>
              <dt className="text-muted">RAM available</dt>
              <dd className="font-medium text-fg">{size(hardware.memory_available_bytes)} / {size(hardware.memory_total_bytes)}</dd>
            </div>
            <div>
              <dt className="text-muted">SelfX storage free</dt>
              <dd className="font-medium text-fg">{size(hardware.disk_free_bytes)}</dd>
            </div>
            <div>
              <dt className="text-muted">NVIDIA memory available</dt>
              <dd className="font-medium text-fg">
                {gpu == null ? "Not visible to the API" : gpu.length === 0 ? "No device reported" : (
                  <ul className="space-y-0.5">
                    {gpu.map((device, index) => (
                      <li key={index}>{gpu.length > 1 ? `GPU ${index + 1} · ` : ""}{size(device.free_bytes)} / {size(device.total_bytes)}</li>
                    ))}
                  </ul>
                )}
              </dd>
            </div>
          </dl>
        </>
      )}

      {recommendation && (
        <div className="mt-4 rounded-xl border border-line bg-surface-2 p-3">
          <p className="text-sm font-semibold text-fg">Suggested starting profile</p>
          {recommendedModel && (
            <p className="mt-1 break-words text-sm text-fg">
              {recommendedModel}{recommendation.context_tokens !== null && ` · ${recommendation.context_tokens.toLocaleString()} tokens`}
            </p>
          )}
          <p className="mt-1 text-xs text-muted">{recommendation.note}</p>
          {recommendedModel && (
            <button type="button" onClick={() => onUseModel(recommendedModel)} className="mt-2 min-h-8 text-sm font-medium text-primary underline underline-offset-4">
              Fill model pull field
            </button>
          )}
        </div>
      )}
    </section>
  );
}
