import { Check } from "lucide-react";
import type { WorkflowPlan } from "../api";

const actions: Record<string, string> = {
  "pdf-compress": "Compress PDF",
  "pdf-rotate": "Rotate PDF",
  "pdf-extract-text": "Extract PDF text",
  "ocr-pdf": "Make PDF searchable",
  "image-convert": "Convert image",
  "image-optimize": "Optimize image",
  "video-trim": "Trim video",
  "audio-extract": "Extract audio",
  "subtitle-convert": "Convert subtitles",
  transcribe: "Transcribe recording",
  "transcript-pdf": "Create transcript PDF and captions",
  "export-pdf": "Format a timestamped PDF",
  "export-srt": "Export captions and timed text",
};

function readableName(value: string): string {
  const name = value.replace(/[-_]/g, " ");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export default function WorkflowSteps({
  plan, activeStep, complete = false,
}: { plan: WorkflowPlan; activeStep?: number; complete?: boolean }) {
  return (
    <ol className="mt-3 space-y-3">
      {plan.steps.map((step, index) => {
        const [sourceId, output] = step.input.split(".");
        const sourceIndex = plan.steps.findIndex((earlier) => earlier.id === sourceId);
        const inputLabel = step.input === "source" ? "Source file" : `Step ${sourceIndex + 1} · ${readableName(output)}`;
        const active = activeStep === index + 1;
        const done = complete || (activeStep !== undefined && index + 1 < activeStep);
        return (
          <li key={step.id} aria-current={active ? "step" : undefined}
            className={`flex items-start gap-2 rounded-lg ${active ? "bg-primary-soft p-2" : ""}`}>
            <span className={`grid size-6 shrink-0 place-items-center rounded-lg text-xs font-semibold ${active ? "bg-primary text-primary-fg" : "bg-primary-soft text-primary"}`}>
              {done ? <Check aria-hidden="true" className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0">
              <p className="break-words text-sm font-medium text-fg">{actions[step.action] ?? readableName(step.action)}</p>
              <p className="mt-0.5 text-xs text-muted">{inputLabel}</p>
              {active && <span className="mt-1 block text-xs font-semibold text-primary">In progress</span>}
              {done && <span className="sr-only">Complete</span>}
              {Object.keys(step.params).length > 0 && (
                <dl className="mt-1 space-y-0.5 text-xs text-muted">
                  {Object.entries(step.params).map(([name, value]) => (
                    <div className="flex flex-wrap gap-x-1" key={name}>
                      <dt className="font-medium">{readableName(name)}</dt>
                      <dd className="break-all">{Array.isArray(value) ? value.join(", ") : String(value ?? "")}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
