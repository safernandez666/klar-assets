import { useEffect, useState } from "react";
import { Moon, Sun, ShieldCheck, FileDown } from "lucide-react";
import { Button } from "./ui/button";
import { formatDate } from "../lib/utils";
import type { SyncRun } from "../types";

interface LayoutProps {
  children: React.ReactNode;
  lastSync: SyncRun | null;
  onSync: () => void;
  syncing: boolean;
  onExportPdf?: () => void;
  exporting?: boolean;
}

export function Layout({
  children,
  lastSync,
  onSync,
  syncing,
  onExportPdf,
  exporting,
}: LayoutProps) {
  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return true;
    const stored = localStorage.getItem("theme");
    if (stored) return stored === "dark";
    return true; // dark-first
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      root.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [dark]);

  const syncStatus = lastSync?.status === "success" ? "success" : "warning";

  return (
    <div className="min-h-screen bg-background text-foreground antialiased transition-colors">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-500/20">
              <ShieldCheck className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">
                Device Inventory Normalizer
              </h1>
              <p className="text-xs text-muted">
                Last sync: {lastSync ? formatDate(lastSync.finished_at || lastSync.started_at) : "N/A"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span
              className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                syncStatus === "success"
                  ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                  : "border-amber-500/20 bg-amber-500/10 text-amber-400"
              }`}
            >
              {syncStatus === "success" ? "Healthy" : "Partial"}
            </span>

            {onExportPdf && (
              <Button
                variant="outline"
                size="sm"
                onClick={onExportPdf}
                disabled={exporting}
                className="gap-2"
              >
                {exporting ? (
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                ) : (
                  <FileDown className="h-4 w-4" />
                )}
                {exporting ? "Exporting..." : "Export PDF"}
              </Button>
            )}

            <Button
              size="sm"
              onClick={onSync}
              disabled={syncing}
              className="gap-2"
            >
              {syncing ? (
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
              )}
              {syncing ? "Syncing..." : "Sync now"}
            </Button>

            <Button
              variant="ghost"
              size="icon"
              onClick={() => setDark((d) => !d)}
              aria-label="Toggle theme"
            >
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-6 py-8">
        {children}
      </main>
    </div>
  );
}
