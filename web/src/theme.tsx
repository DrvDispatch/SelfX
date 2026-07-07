import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type ThemeChoice = "light" | "dark" | "system";
type Resolved = "light" | "dark";

interface ThemeCtx {
  choice: ThemeChoice;
  resolved: Resolved;
  setChoice: (c: ThemeChoice) => void;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx | null>(null);
const KEY = "selfx-theme";

function systemPref(): Resolved {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(resolved: Resolved) {
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(
    () => (localStorage.getItem(KEY) as ThemeChoice) || "system",
  );
  const [resolved, setResolved] = useState<Resolved>(() =>
    (localStorage.getItem(KEY) as ThemeChoice) === "light"
      ? "light"
      : (localStorage.getItem(KEY) as ThemeChoice) === "dark"
        ? "dark"
        : systemPref(),
  );

  useEffect(() => {
    const r = choice === "system" ? systemPref() : choice;
    setResolved(r);
    apply(r);
  }, [choice]);

  useEffect(() => {
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const r = systemPref();
      setResolved(r);
      apply(r);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = (c: ThemeChoice) => {
    localStorage.setItem(KEY, c);
    setChoiceState(c);
  };
  const toggle = () => setChoice(resolved === "dark" ? "light" : "dark");

  return (
    <Ctx.Provider value={{ choice, resolved, setChoice, toggle }}>{children}</Ctx.Provider>
  );
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
