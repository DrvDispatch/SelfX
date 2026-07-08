import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BookOpen, Boxes, ChevronDown, Clipboard, Cpu, Layers, LayoutGrid, ListChecks, LogOut, Moon, Search, Shield, Sparkles, Sun, Workflow, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import { imageFromPasteEvent } from "../clipboard";
import CommandPalette from "./CommandPalette";

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary-soft text-primary"
      : "text-muted hover:bg-surface-2 hover:text-fg",
  ].join(" ");
}

// Secondary / power-user pages, tucked under the "More" menu so the header never wraps.
const MORE_ITEMS: { to: string; label: string; icon: LucideIcon; admin?: boolean }[] = [
  { to: "/batch", label: "Batch", icon: Layers },
  { to: "/pipeline", label: "Pipeline", icon: Workflow },
  { to: "/quick-tools", label: "Quick Tools", icon: Boxes },
  { to: "/models", label: "AI Models", icon: Cpu, admin: true },
  { to: "/admin", label: "Admin", icon: Shield, admin: true },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { resolved, toggle } = useTheme();
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Paste a screenshot ANYWHERE → route it to the Paste page ready to use. Ignore
  // pastes aimed at editable fields so normal text paste (search, forms, chat) is untouched.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) {
        return;
      }
      const file = imageFromPasteEvent(e);
      if (!file) return;
      e.preventDefault();
      navigate("/paste", { state: { pastedImage: file } });
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [navigate]);

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
          <NavLink to="/" className="flex items-center gap-2 text-lg font-extrabold tracking-tight text-fg">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary text-sm text-primary-fg">
              S
            </span>
            Self<span className="text-primary">X</span>
          </NavLink>

          <nav className="ml-3 hidden items-center gap-1 md:flex">
            <NavLink to="/" end className={navClass}>
              <LayoutGrid className="h-4 w-4" /> Tools
            </NavLink>
            <NavLink to="/assistant" className={navClass}>
              <Sparkles className="h-4 w-4" /> Assistant
            </NavLink>
            <NavLink to="/knowledge" className={navClass}>
              <BookOpen className="h-4 w-4" /> Knowledge
            </NavLink>
            <NavLink to="/paste" className={navClass}>
              <Clipboard className="h-4 w-4" /> Paste
            </NavLink>
            <NavLink to="/jobs" className={navClass}>
              <ListChecks className="h-4 w-4" /> Jobs
            </NavLink>

            {/* Overflow menu keeps the header from wrapping as features grow */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setMoreOpen((o) => !o)}
                className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
              >
                More <ChevronDown className={`h-4 w-4 transition-transform ${moreOpen ? "rotate-180" : ""}`} />
              </button>
              {moreOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMoreOpen(false)} />
                  <div className="absolute right-0 top-full z-20 mt-1.5 w-48 rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow-pop)]">
                    {MORE_ITEMS.filter((it) => !it.admin || user?.is_admin).map((it) => {
                      const Icon = it.icon;
                      return (
                        <NavLink
                          key={it.to}
                          to={it.to}
                          onClick={() => setMoreOpen(false)}
                          className={({ isActive }) =>
                            `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                              isActive ? "bg-primary-soft text-primary" : "text-fg hover:bg-surface-2"
                            }`
                          }
                        >
                          <Icon className="h-4 w-4 shrink-0" /> {it.label}
                        </NavLink>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          </nav>

          <div className="flex-1" />

          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            title="Search (⌘K)"
            className="hidden items-center gap-2 rounded-full bg-surface-2 py-1.5 pl-3 pr-1.5 text-sm text-muted transition-colors hover:text-fg sm:flex"
          >
            <Search className="h-4 w-4" />
            <span className="text-faint">Search</span>
            <kbd className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-faint">⌘K</kbd>
          </button>

          <button
            type="button"
            onClick={toggle}
            title={resolved === "dark" ? "Switch to light" : "Switch to dark"}
            className="grid h-9 w-9 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            {resolved === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

          <div className="flex items-center gap-2 rounded-full bg-surface-2 py-1 pl-3 pr-1">
            <span className="max-w-[9rem] truncate text-sm text-fg" title={user?.username}>
              {user?.username}
            </span>
            {user?.is_admin && (
              <span className="rounded-full bg-primary-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase text-primary">
                admin
              </span>
            )}
            <button
              type="button"
              onClick={onLogout}
              title="Log out"
              className="grid h-7 w-7 place-items-center rounded-full text-muted transition-colors hover:bg-surface hover:text-danger"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="animate-in mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <Outlet />
      </main>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
