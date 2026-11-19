import { Suspense, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BookOpen, Boxes, ChevronDown, Clipboard, Cpu, Layers, LayoutGrid, ListChecks, LogOut,
  Menu, Moon, Search, Shield, SlidersHorizontal, Sparkles, Sun, Workflow, X, type LucideIcon,
} from "lucide-react";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import { imageFromPasteEvent } from "../clipboard";
import Brand from "./Brand";
import CommandPalette from "./CommandPalette";
import RouteErrorBoundary from "./RouteErrorBoundary";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  matches?: string[];
}

const PRIMARY: NavItem[] = [
  { to: "/", label: "Create", icon: Sparkles },
  { to: "/tools", label: "Tools", icon: LayoutGrid, matches: ["/tool/"] },
  { to: "/recipes", label: "Recipes", icon: BookOpen },
  { to: "/jobs", label: "Activity", icon: ListChecks, matches: ["/runs/"] },
];

const UTILITIES: NavItem[] = [
  { to: "/paste", label: "Paste image", icon: Clipboard },
  { to: "/batch", label: "Batch", icon: Layers },
  { to: "/pipeline", label: "Pipeline", icon: Workflow },
  { to: "/quick-tools", label: "Quick tools", icon: Boxes },
  { to: "/assistant", label: "Assistant", icon: Sparkles },
  { to: "/knowledge", label: "Knowledge", icon: BookOpen },
];

const SETTINGS: NavItem[] = [
  { to: "/models", label: "AI models", icon: Cpu },
  { to: "/admin", label: "Admin", icon: Shield },
];

function SidebarLinks({ items, path }: { items: NavItem[]; path: string }) {
  return items.map(({ to, label, icon: Icon, matches }) => {
    const current = path === to || matches?.some((prefix) => path.startsWith(prefix));
    return (
      <Link key={to} to={to} aria-current={current ? "page" : undefined}
        className={`flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors ${current ? "bg-primary-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
        <Icon className="size-[17px] shrink-0" aria-hidden="true" />
        {label}
      </Link>
    );
  });
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { resolved, toggle } = useTheme();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const drawer = useRef<HTMLDialogElement>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const themeLabel = resolved === "dark" ? "Switch to light theme" : "Switch to dark theme";

  useEffect(() => {
    drawer.current?.close();
    setPaletteOpen(false);
  }, [pathname]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        drawer.current?.close();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && (target.matches("input, textarea, select") || target.isContentEditable)) return;
      const file = imageFromPasteEvent(event);
      if (file) {
        event.preventDefault();
        navigate("/paste", { state: { pastedImage: file } });
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [navigate]);

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-full lg:grid lg:grid-cols-[14.5rem_minmax(0,1fr)]">
      <a href="#workspace-content" className="sr-only z-[60] rounded-lg bg-surface p-3 focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh overflow-y-auto border-r border-line bg-surface lg:flex lg:flex-col">
        <Link to="/" aria-label="SelfX home" className="mx-4 my-5 self-start rounded-lg p-1">
          <Brand />
        </Link>
        <nav aria-label="Workspace" className="space-y-1 px-3">
          <SidebarLinks items={PRIMARY} path={pathname} />
        </nav>
        <div className="mx-5 my-5 h-px shrink-0 bg-line" />
        <nav aria-label="More tools" className="space-y-1 px-3">
          <SidebarLinks items={UTILITIES} path={pathname} />
        </nav>
        {user?.is_admin && (
          <details className="group mx-3 mt-auto mb-4 pt-4" open={SETTINGS.some(({ to }) => pathname === to) || undefined}>
            <summary className="flex min-h-10 cursor-pointer list-none items-center gap-3 rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg [&::-webkit-details-marker]:hidden">
              <SlidersHorizontal aria-hidden="true" className="size-[17px]" />
              <span className="flex-1">Administration</span>
              <ChevronDown aria-hidden="true" className="size-4 group-open:rotate-180" />
            </summary>
            <nav aria-label="Administration" className="mt-1 space-y-1 pl-3">
              <SidebarLinks items={SETTINGS} path={pathname} />
            </nav>
          </details>
        )}
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
          <div className="mx-auto flex h-[3.8rem] max-w-[84rem] items-center gap-2 px-4 sm:px-7">
            <button type="button" aria-label="Open menu" onClick={() => drawer.current?.showModal()}
              className="-ml-1 grid size-10 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg lg:hidden">
              <Menu aria-hidden="true" className="size-5" />
            </button>
            <Link to="/" aria-label="SelfX home" className="rounded-lg lg:hidden"><Brand /></Link>
            <button type="button" aria-label="Search tools and pages" onClick={() => setPaletteOpen(true)}
              className="ml-auto flex min-h-10 items-center gap-2 rounded-lg px-2.5 text-sm text-muted hover:bg-surface-2 hover:text-fg lg:ml-0 lg:border lg:border-line lg:bg-surface">
              <Search aria-hidden="true" className="size-4.5" />
              <span className="hidden lg:inline">Search tools and pages</span>
              <kbd aria-hidden="true" className="ml-2 hidden rounded border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted lg:inline">Ctrl K</kbd>
            </button>
            <div className="hidden flex-1 lg:block" />
            <button type="button" aria-label={themeLabel} title={themeLabel} onClick={toggle}
              className="grid size-10 shrink-0 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg">
              {resolved === "dark" ? <Sun aria-hidden="true" className="size-[17px]" /> : <Moon aria-hidden="true" className="size-[17px]" />}
            </button>
            <div className="flex h-9 shrink-0 items-center gap-1 border-l border-line pl-1.5 sm:gap-2 sm:pl-3">
              <span className="hidden max-w-36 truncate text-sm font-medium text-fg sm:inline" title={user?.username}>{user?.username}</span>
              <button type="button" aria-label="Log out" title="Log out" onClick={onLogout}
                className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-danger">
                <LogOut aria-hidden="true" className="size-4" />
              </button>
            </div>
          </div>
        </header>

        <main id="workspace-content" tabIndex={-1} className="mx-auto max-w-[80rem] px-4 pt-6 pb-[calc(6rem+env(safe-area-inset-bottom))] sm:px-7 sm:pt-8 lg:pb-11">
          <RouteErrorBoundary key={pathname}>
            <Suspense fallback={<p role="status" className="text-sm text-muted">Loading page…</p>}>
              <Outlet />
            </Suspense>
          </RouteErrorBoundary>
        </main>
      </div>

      <nav aria-label="Workspace shortcuts" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden">
        {PRIMARY.map(({ to, label, icon: Icon, matches }) => {
          const current = pathname === to || matches?.some((prefix) => pathname.startsWith(prefix));
          return (
            <Link key={to} to={to} aria-current={current ? "page" : undefined}
              className={`flex min-h-[3.65rem] flex-col items-center justify-center gap-1 px-1 text-[11px] font-semibold ${current ? "text-primary" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
              <span className={`grid h-6 w-9 place-items-center rounded-lg ${current ? "bg-primary-soft" : ""}`}>
                <Icon aria-hidden="true" className="size-4.5" />
              </span>
              {label}
            </Link>
          );
        })}
      </nav>

      <dialog ref={drawer} aria-label="Workspace menu" onClick={(event) => { if (event.target === event.currentTarget) drawer.current?.close(); }}
        className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-[min(19rem,90vw)] max-w-none border-r border-line bg-surface p-0 text-fg shadow-[var(--shadow-pop)] backdrop:bg-black/50">
        <div className="min-h-full p-4">
          <div className="mb-4 flex items-center justify-between">
            <Brand />
            <button type="button" aria-label="Close menu" onClick={() => drawer.current?.close()}
              className="grid size-10 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-fg">
              <X aria-hidden="true" className="size-5" />
            </button>
          </div>
          <nav className="space-y-1" onClick={(event) => { if ((event.target as Element).closest("a")) drawer.current?.close(); }}>
            <SidebarLinks items={PRIMARY} path={pathname} />
            <div className="my-3 h-px bg-line" />
            <SidebarLinks items={UTILITIES} path={pathname} />
            {user?.is_admin && <><div className="my-3 h-px bg-line" /><SidebarLinks items={SETTINGS} path={pathname} /></>}
          </nav>
        </div>
      </dialog>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
