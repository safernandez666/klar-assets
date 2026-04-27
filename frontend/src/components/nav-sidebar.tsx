import { useEffect, useState } from "react";
import {
  Search,
  Users,
  Settings,
  Moon,
  Sun,
  LogOut,
  User,
  Home,
  ShieldCheck,
} from "lucide-react";

export function NavSidebar() {
  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("theme") === "dark";
  });
  const [currentUser, setCurrentUser] = useState("user");
  const path = window.location.pathname;

  useEffect(() => {
    fetch("/auth/me").then(r => r.json()).then(d => setCurrentUser(d.user || "user")).catch(() => {});
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    const root = document.documentElement;
    if (next) { root.classList.add("dark"); localStorage.setItem("theme", "dark"); }
    else { root.classList.remove("dark"); localStorage.setItem("theme", "light"); }
  };

  const navItem = (href: string, icon: React.ReactNode, label: string, color: string) => {
    const isActive = path === href || (href === "/" && path === "/");
    return (
      <a
        href={href}
        className={`group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none ${
          isActive ? `${color} bg-card` : `hover:${color}`
        }`}
        aria-label={label}
      >
        {icon}
        <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
          {label}
        </span>
      </a>
    );
  };

  return (
    <div className="fixed left-0 top-0 z-40 flex h-screen w-14 flex-col items-center border-r border-border bg-card/95 pt-20 pb-4 backdrop-blur">
      <div className="flex flex-col items-center gap-1 flex-1">
        {navItem("/", <Home className="h-5 w-5 text-blue-400" />, "Dashboard", "bg-blue-500/10")}
        {navItem("/search", <Search className="h-5 w-5 text-violet-400" />, "Asset Search", "bg-violet-500/10")}
        {navItem("/people", <Users className="h-5 w-5 text-cyan-400" />, "People", "bg-cyan-500/10")}
        {navItem("/controls", <ShieldCheck className="h-5 w-5 text-emerald-400" />, "Controls", "bg-emerald-500/10")}
      </div>

      {/* Bottom */}
      <div className="flex flex-col items-center gap-1">
        {navItem("/settings", <Settings className="h-5 w-5 text-muted" />, "Settings", "bg-card")}

        <button
          type="button"
          onClick={toggleTheme}
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-card focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          aria-label="Toggle theme"
        >
          {dark ? <Sun className="h-5 w-5 text-amber-300" /> : <Moon className="h-5 w-5 text-blue-400" />}
          <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
            {dark ? "Light mode" : "Dark mode"}
          </span>
        </button>

        <div className="my-1 h-px w-6 bg-border" />

        <div className="group relative flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
          <User className="h-4 w-4 text-accent" />
          <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
            {currentUser}
          </span>
        </div>

        <button
          type="button"
          onClick={() => { window.location.href = "/auth/logout"; }}
          className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
          aria-label="Sign out"
        >
          <LogOut className="h-4 w-4 text-red-400" />
          <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
            Sign out
          </span>
        </button>
      </div>
    </div>
  );
}
