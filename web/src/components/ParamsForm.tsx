import type { ReactElement } from "react";
import type { ParamProperty, ParamsSchema } from "../types";

interface Props {
  schema: ParamsSchema;
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  disabled?: boolean;
}

const inputClass =
  "w-full rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm text-fg " +
  "outline-none transition-colors placeholder:text-faint focus:border-primary disabled:opacity-60";

function Field({
  name,
  prop,
  required,
  value,
  onChange,
  disabled,
}: {
  name: string;
  prop: ParamProperty;
  required: boolean;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}) {
  const label = prop.title ?? name;
  const id = `param-${name}`;

  let control: ReactElement;
  if (prop.enum && prop.enum.length > 0) {
    control = (
      <select
        id={id}
        className={inputClass}
        value={value === undefined || value === null ? "" : String(value)}
        disabled={disabled}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          // Map back to the original enum member to preserve its type.
          const match = prop.enum?.find((opt) => String(opt) === raw);
          onChange(match ?? raw);
        }}
      >
        {value === undefined && (
          <option value="" disabled={required}>
            {required ? "Select…" : "—"}
          </option>
        )}
        {prop.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  } else if (prop.type === "boolean") {
    return (
      <label className="flex cursor-pointer items-start gap-2.5 py-1">
        <input
          id={id}
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-primary"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>
          <span className="block text-sm font-medium text-fg">{label}</span>
          {prop.description && (
            <span className="block text-xs text-muted">
              {prop.description}
            </span>
          )}
        </span>
      </label>
    );
  } else if (prop.type === "number" || prop.type === "integer") {
    control = (
      <input
        id={id}
        type="number"
        className={inputClass}
        value={typeof value === "number" ? value : ""}
        min={prop.minimum}
        max={prop.maximum}
        step={prop.type === "integer" ? 1 : "any"}
        disabled={disabled}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const num =
            prop.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(num) ? undefined : num);
        }}
      />
    );
  } else if (prop.format === "multiline") {
    control = (
      <textarea
        id={id}
        rows={4}
        className={inputClass}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  } else {
    control = (
      <input
        id={id}
        type="text"
        className={inputClass}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-fg">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </label>
      {control}
      {prop.description && (
        <p className="mt-1 text-xs text-muted">{prop.description}</p>
      )}
    </div>
  );
}

export default function ParamsForm({
  schema,
  values,
  onChange,
  disabled = false,
}: Props) {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const entries = Object.entries(properties);

  if (entries.length === 0) {
    return <p className="text-sm text-muted">This tool has no options.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {entries.map(([name, prop]) => (
        <Field
          key={name}
          name={name}
          prop={prop}
          required={required.has(name)}
          value={values[name]}
          onChange={(v) => onChange(name, v)}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
