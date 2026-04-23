import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Zap,
  X,
  AlertOctagon,
  AlertTriangle,
  Info,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSpreadsheet,
  Download,
  RefreshCw,
  FileDown,
  RotateCw,
  Moon,
  Sun,
  Search,
  LogOut,
  User,
  Users,
} from "lucide-react";
import type { Insight } from "../types";

interface SidebarProps {
  insights: Insight[];
  onRefreshInsights?: () => void;
  refreshing?: boolean;
  onSync?: () => void;
  syncing?: boolean;
  onExportPdf?: () => void;
  exporting?: boolean;
}

const PRIORITY_CONFIG: Record<string, {
  icon: typeof AlertOctagon;
  color: string;
  bg: string;
  border: string;
  label: string;
  sortOrder: number;
}> = {
  critical: { icon: AlertOctagon, color: "text-red-400", bg: "bg-red-500/5", border: "border-red-500/20", label: "CRITICAL", sortOrder: 0 },
  high: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/20", label: "HIGH", sortOrder: 1 },
  medium: { icon: Info, color: "text-blue-400", bg: "bg-blue-500/5", border: "border-blue-500/20", label: "MEDIUM", sortOrder: 2 },
  low: { icon: Info, color: "text-muted", bg: "bg-neutral-500/5", border: "border-neutral-500/20", label: "LOW", sortOrder: 3 },
  success: { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/5", border: "border-emerald-500/20", label: "OK", sortOrder: 5 },
  info: { icon: Info, color: "text-blue-400", bg: "bg-blue-500/5", border: "border-blue-500/20", label: "INFO", sortOrder: 4 },
};

function ActionItem({ action, index }: { action: Insight; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = PRIORITY_CONFIG[action.priority] || PRIORITY_CONFIG.info;
  const Icon = cfg.icon;

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: 0.05 + index * 0.03 }}
      role="listitem"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={`w-full rounded-lg border ${cfg.border} ${cfg.bg} p-3 text-left transition-colors hover:bg-card/50 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none`}
      >
        <div className="flex items-start gap-2.5">
          <div className={`mt-0.5 shrink-0 ${cfg.color}`} aria-hidden="true">
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-bold uppercase ${cfg.color} ${cfg.bg} border ${cfg.border}`}>
                {cfg.label}
              </span>
              <h4 className="text-xs font-semibold text-pretty leading-snug">{action.title}</h4>
            </div>
            <AnimatePresence>
              {expanded && (
                <motion.p
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.15 }}
                  className="mt-1.5 text-[11px] leading-relaxed text-muted"
                >
                  {action.description}
                </motion.p>
              )}
            </AnimatePresence>
          </div>
          <div className="mt-0.5 shrink-0 text-muted opacity-40" aria-hidden="true">
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </div>
        </div>
      </button>
    </motion.div>
  );
}

export function Sidebar({ insights, onRefreshInsights, refreshing, onSync, syncing, onExportPdf, exporting }: SidebarProps) {
  const [open, setOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const sorted = [...insights].sort((a, b) => {
    const aOrder = PRIORITY_CONFIG[a.priority]?.sortOrder ?? 99;
    const bOrder = PRIORITY_CONFIG[b.priority]?.sortOrder ?? 99;
    return aOrder - bOrder;
  });

  const urgent = sorted.filter((a) => a.priority === "critical" || a.priority === "high");
  const other = sorted.filter((a) => a.priority !== "critical" && a.priority !== "high");

  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return true;
    return localStorage.getItem("theme") === "dark";
  });

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    const root = document.documentElement;
    if (next) { root.classList.add("dark"); localStorage.setItem("theme", "dark"); }
    else { root.classList.remove("dark"); localStorage.setItem("theme", "light"); }
  };

  return (
    <>
      {/* Fixed sidebar rail */}
      <div className="fixed left-0 top-0 z-40 flex h-screen w-14 flex-col items-center border-r border-border bg-card/95 pt-20 pb-4 backdrop-blur">
        <div className="flex flex-col items-center gap-1 flex-1">
          {/* Sync */}
          <button
            type="button"
            onClick={onSync}
            disabled={syncing}
            className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-blue-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-50"
            aria-label="Sync now"
          >
            <RotateCw className={`h-5 w-5 text-blue-400 ${syncing ? "animate-spin" : ""}`} />
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              {syncing ? "Syncing..." : "Sync now"}
            </span>
          </button>

          {/* Asset Search */}
          <a
            href="/search"
            className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-violet-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            aria-label="Asset Search"
          >
            <Search className="h-5 w-5 text-violet-400" />
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              Asset Search
            </span>
          </a>

          {/* People */}
          <a
            href="/people"
            className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-cyan-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            aria-label="People"
          >
            <Users className="h-5 w-5 text-cyan-400" />
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              People
            </span>
          </a>

          {/* Quick Actions */}
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-amber-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
            aria-label="Quick Actions"
          >
            <Zap className="h-5 w-5 text-amber-400" />
            {urgent.length > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white">
                {urgent.length}
              </span>
            )}
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              Quick Actions
            </span>
          </button>

          {/* Separator */}
          <div className="my-1 h-px w-6 bg-border" />

          {/* Export — grouped */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setExportOpen((v) => !v)}
              className="group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-emerald-500/10 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
              aria-label="Export"
            >
              <Download className={`h-5 w-5 text-emerald-400 ${exporting ? "animate-pulse" : ""}`} />
              <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                Export
              </span>
            </button>
            <AnimatePresence>
              {exportOpen && (
                <motion.div
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -4 }}
                  transition={{ duration: 0.15 }}
                  className="absolute left-full top-0 ml-2 z-50 w-40 rounded-xl border border-border bg-card shadow-xl overflow-hidden"
                >
                  <button
                    type="button"
                    onClick={() => { onExportPdf?.(); setExportOpen(false); }}
                    disabled={exporting}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-xs hover:bg-background transition-colors disabled:opacity-50"
                  >
                    <FileDown className="h-4 w-4 text-red-400" />
                    {exporting ? "Exporting..." : "PDF Report"}
                  </button>
                  <a
                    href="/api/export/csv"
                    onClick={() => setExportOpen(false)}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-xs hover:bg-background transition-colors"
                  >
                    <FileSpreadsheet className="h-4 w-4 text-blue-400" />
                    CSV
                  </a>
                  <a
                    href="/api/export/xlsx"
                    onClick={() => setExportOpen(false)}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-xs hover:bg-background transition-colors"
                  >
                    <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
                    Excel
                  </a>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Bottom section: theme + user + logout */}
        <div className="mt-auto mb-4 flex flex-col items-center gap-1">
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

          {/* User avatar */}
          <div className="group relative flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
            <User className="h-4 w-4 text-accent" />
            <span className="pointer-events-none absolute left-full ml-3 whitespace-nowrap rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
              admin
            </span>
          </div>

          {/* Logout */}
          <button
            type="button"
            onClick={async () => {
              try { await fetch("/auth/logout", { method: "POST" }); } catch {}
              document.cookie = "klar_session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
              window.location.replace("/");
            }}
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

      {/* Slide-over panel */}
      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 z-[55] bg-black/40 backdrop-blur-sm"
              onClick={() => setOpen(false)}
            />

            {/* Panel */}
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
              className="fixed right-0 top-0 z-[60] flex h-screen w-full max-w-sm flex-col border-l border-border bg-background shadow-2xl"
            >
              {/* Panel header */}
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <div className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-amber-400" aria-hidden="true" />
                  <h2 className="text-sm font-semibold">Quick Actions</h2>
                  {urgent.length > 0 && (
                    <span className="rounded-full bg-red-500/10 border border-red-500/20 px-2 py-0.5 text-[10px] font-semibold text-red-400">
                      {urgent.length} urgent
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="rounded-lg p-1.5 transition-colors hover:bg-card focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
                  aria-label="Close panel"
                >
                  <X className="h-4 w-4 text-muted" />
                </button>
              </div>

              {/* Panel content — scrollable */}
              <div className="flex-1 overflow-y-auto px-5 py-4">
                {urgent.length > 0 && (
                  <div className="mb-5" role="list" aria-label="Urgent actions">
                    <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-red-400/70">
                      Requires attention
                    </h3>
                    <div className="space-y-2">
                      {urgent.map((action, i) => (
                        <ActionItem key={`u-${i}`} action={action} index={i} />
                      ))}
                    </div>
                  </div>
                )}

                {other.length > 0 && (
                  <div role="list" aria-label="Recommendations">
                    <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted/70">
                      Recommendations
                    </h3>
                    <div className="space-y-2">
                      {other.map((action, i) => (
                        <ActionItem key={`o-${i}`} action={action} index={urgent.length + i} />
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Panel footer */}
              <div className="border-t border-border px-5 py-3 flex items-center justify-between">
                <p className="text-[10px] text-muted">
                  AI-powered analysis
                </p>
                {onRefreshInsights && (
                  <button
                    type="button"
                    onClick={onRefreshInsights}
                    disabled={refreshing}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[11px] font-medium transition-colors hover:bg-card focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none disabled:opacity-50"
                  >
                    <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
                    {refreshing ? "Analyzing..." : "Re-analyze"}
                  </button>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
