import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Boxes, LayoutGrid, ListChecks, LogOut, Moon, Shield, Sun } from "lucide-react";
import { useAuth } from "../auth";
import { useTheme } from "../theme";

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary-soft text-primary"
      : "text-muted hover:bg-surface-2 hover:text-fg",
  ].join(" ");
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { resolved, toggle } = useTheme();
  const navigate = useNavigate();

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

          <nav className="ml-3 hidden items-center gap-1 sm:flex">
            <NavLink to="/" end className={navClass}>
              <LayoutGrid className="h-4 w-4" /> Tools
            </NavLink>
            <NavLink to="/jobs" className={navClass}>
              <ListChecks className="h-4 w-4" /> Jobs
            </NavLink>
            <NavLink to="/quick-tools" className={navClass}>
              <Boxes className="h-4 w-4" /> Quick Tools
            </NavLink>
            {user?.is_admin && (
              <NavLink to="/admin" className={navClass}>
                <Shield className="h-4 w-4" /> Admin
              </NavLink>
            )}
          </nav>

          <div className="flex-1" />

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
    </div>
  );
}
