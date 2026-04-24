import { ShieldCheck } from "lucide-react";
import { formatDate } from "../lib/utils";
import type { SyncRun } from "../types";

interface LayoutProps {
  children: React.ReactNode;
  lastSync: SyncRun | null;
}

export function Layout({ children, lastSync }: LayoutProps) {
  const syncStatus = lastSync?.status === "success" ? "success" : "warning";

  return (
    <div className="min-h-screen bg-background text-foreground antialiased transition-colors">
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-500/20">
              <ShieldCheck className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">
                Klar Device Normalizer
              </h1>
              <p className="text-xs text-muted">
                Last sync: {lastSync ? formatDate(lastSync.finished_at || lastSync.started_at) : "N/A"}
              </p>
            </div>
          </div>

          <span
            className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
              syncStatus === "success"
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                : "border-amber-500/20 bg-amber-500/10 text-amber-400"
            }`}
          >
            {syncStatus === "success" ? "Healthy" : "Partial"}
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-6 py-8">
        {children}
      </main>
    </div>
  );
}
