import type { ToolInfo } from "../types";
import ParamsForm from "./ParamsForm";

const primary = ["task", "language", "output"];
const transcriptionLabels = {
  task: { transcribe: "Keep the spoken language", translate: "Translate to English" },
  output: {
    txt: "Plain text (.txt)",
    srt: "Subtitles (.srt)",
    vtt: "Web captions (.vtt)",
    json: "Timed transcript (.json)",
    all: "All formats",
  },
  model: { auto: "Server default" },
};

interface Props {
  tool: ToolInfo;
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  disabled: boolean;
}

export default function ToolOptions({ tool, ...form }: Props) {
  if (tool.slug !== "transcribe") return <ParamsForm schema={tool.params_schema} {...form} />;

  const { properties = {}, required = [] } = tool.params_schema;
  const basic = primary.filter((name) => name in properties).map((name) => [name, properties[name]]);
  const advanced = Object.entries(properties).filter(([name]) => !primary.includes(name));

  return (
    <>
      <ParamsForm
        schema={{ properties: Object.fromEntries(basic), required }}
        optionLabels={transcriptionLabels}
        {...form}
      />
      {advanced.length > 0 && (
        <details className="mt-4 rounded-xl border border-line bg-surface">
          <summary className="cursor-pointer rounded-xl px-3.5 py-2.5 text-sm font-medium text-fg">
            Advanced transcription settings
          </summary>
          <div className="border-t border-line p-3.5">
            <ParamsForm
              schema={{ properties: Object.fromEntries(advanced), required }}
              optionLabels={transcriptionLabels}
              {...form}
            />
          </div>
        </details>
      )}
    </>
  );
}
