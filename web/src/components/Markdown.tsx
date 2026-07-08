import { useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

function CodeBlock({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ref.current?.textContent ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <div className="group/code relative my-2">
      <pre
        ref={ref}
        className="overflow-x-auto rounded-xl border border-line bg-surface-2 p-3 font-mono text-[13px] leading-relaxed text-fg"
      >
        {children}
      </pre>
      <button
        onClick={() => void copy()}
        aria-label="Copy code"
        className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-lg border border-line bg-surface text-faint opacity-0 transition-opacity hover:text-fg group-hover/code:opacity-100"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

/** Renders GFM markdown with token-styled elements. No raw HTML is allowed (safe). */
export default function Markdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-fg">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
          h1: ({ children }) => <h1 className="mb-2 mt-3 text-lg font-bold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-3 text-base font-bold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1.5 mt-2 text-sm font-semibold first:mt-0">{children}</h3>,
          ul: ({ children }) => <ul className="my-1.5 ml-4 list-disc space-y-1 marker:text-faint">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 ml-4 list-decimal space-y-1 marker:text-faint">{children}</ol>,
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary">
              {children}
            </a>
          ),
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-primary/40 pl-3 text-muted">{children}</blockquote>
          ),
          hr: () => <hr className="my-3 border-line" />,
          code: ({ className, children, ...props }) => {
            const isBlock = /language-/.test(className || "") || String(children).includes("\n");
            if (isBlock) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }
            return <code className="rounded bg-surface px-1 py-0.5 font-mono text-[0.85em] font-medium text-primary">{children}</code>;
          },
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-line">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-surface-2">{children}</thead>,
          th: ({ children }) => <th className="border-b border-line px-2.5 py-1.5 text-left font-semibold">{children}</th>,
          td: ({ children }) => <td className="border-b border-line px-2.5 py-1.5">{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
