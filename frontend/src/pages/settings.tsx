import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Clock,
  Server,
  Send,
} from "lucide-react";
import { toast } from "../components/toasts";
import { Card, CardContent } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { formatDate } from "../lib/utils";

interface SourceStatus {
  configured: boolean;
  name: string;
}

interface SyncRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  total_raw_devices: number;
  final_count: number;
  sources_ok: string[];
  sources_failed: string[];
}

interface SettingsData {
  sync_interval_hours: number;
  syncing: boolean;
  version: string;
  build_date: string;
  app_url: string;
  sources: Record<string, SourceStatus>;
  last_runs: SyncRun[];
}

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [interval, setInterval_] = useState(6);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings");
      const json = await res.json();
      setData(json);
      setInterval_(json.sync_interval_hours);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSaveInterval = async () => {
    setSaving(true);
    try {
      await fetch("/api/settings/sync-interval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hours: interval }),
      });
      loadData();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await fetch("/api/sync/trigger", { method: "POST" });
      setTimeout(() => { loadData(); setSyncing(false); }, 5000);
    } catch (e) {
      console.error(e);
      setSyncing(false);
    }
  };

  const statusBadge = (status: string) => {
    if (status === "success") return <Badge variant="success">Success</Badge>;
    if (status === "aborted") return <Badge variant="error">Aborted</Badge>;
    return <Badge variant="warning">{status}</Badge>;
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-4">
          <a href="/" className="rounded-lg p-2 hover:bg-card transition-colors"><ArrowLeft className="h-5 w-5" /></a>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
            <p className="text-xs text-muted">Configuration and sync history</p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6 space-y-6">
        {loading && <p className="text-center text-muted py-8">Loading...</p>}

        {data && (
          <>
            {/* Sync Configuration */}
            <Card>
              <CardContent className="p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted mb-4 flex items-center gap-2">
                  <Clock className="h-4 w-4" /> Sync Configuration
                </h2>
                <div className="flex items-end gap-4">
                  <div>
                    <label className="block text-xs font-medium text-muted mb-1">Sync interval (hours)</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="range" min={1} max={24} value={interval}
                        onChange={(e) => setInterval_(Number(e.target.value))}
                        className="w-48 accent-accent"
                      />
                      <span className="text-lg font-bold w-8">{interval}h</span>
                    </div>
                  </div>
                  <Button size="sm" onClick={handleSaveInterval} disabled={saving || interval === data.sync_interval_hours}>
                    {saving ? "Saving..." : "Save"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing || data.syncing}>
                    <RefreshCw className={`h-4 w-4 mr-1 ${syncing ? "animate-spin" : ""}`} />
                    {syncing ? "Syncing..." : "Sync now"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={async () => {
                    try {
                      const r = await fetch("/api/slack/test", { method: "POST" });
                      const d = await r.json();
                      toast(d.sent
                        ? { type: "success", title: "Slack test sent", duration: 3000 }
                        : { type: "error", title: d.error || "Failed", duration: 4000 });
                    } catch { toast({ type: "error", title: "Connection error", duration: 4000 }); }
                  }}>
                    <Send className="h-4 w-4 mr-1" />
                    Test Slack
                  </Button>
                </div>
                {data.syncing && (
                  <p className="text-xs text-amber-500 mt-2 flex items-center gap-1">
                    <RefreshCw className="h-3 w-3 animate-spin" /> Sync in progress...
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Sources Status */}
            <Card>
              <CardContent className="p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted mb-4 flex items-center gap-2">
                  <Server className="h-4 w-4" /> Sources & Integrations
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {Object.entries(data.sources).map(([key, src]) => (
                    <div key={key} className={`flex items-center gap-3 rounded-lg border p-3 ${
                      src.configured ? "border-emerald-500/20 bg-emerald-500/5" : "border-red-500/20 bg-red-500/5"
                    }`}>
                      {src.configured
                        ? <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
                        : <XCircle className="h-5 w-5 text-red-500 shrink-0" />}
                      <div>
                        <div className="text-xs font-semibold">{src.name}</div>
                        <div className="text-[10px] text-muted">{src.configured ? "Configured" : "Not configured"}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* App Info */}
            <Card>
              <CardContent className="p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted mb-4">App Info</h2>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                  <div>
                    <span className="text-muted">Version</span>
                    <div className="font-mono font-semibold">{data.version}</div>
                  </div>
                  <div>
                    <span className="text-muted">Build Date</span>
                    <div className="font-mono font-semibold">{data.build_date || "N/A"}</div>
                  </div>
                  <div>
                    <span className="text-muted">App URL</span>
                    <div className="font-mono font-semibold truncate">{data.app_url}</div>
                  </div>
                  <div>
                    <span className="text-muted">Sync Interval</span>
                    <div className="font-mono font-semibold">{data.sync_interval_hours}h</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Sync History */}
            <Card>
              <CardContent className="p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted mb-4">Sync History (last 10)</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted">
                        <th className="pb-3 font-medium">#</th>
                        <th className="pb-3 font-medium">Started</th>
                        <th className="pb-3 font-medium">Finished</th>
                        <th className="pb-3 font-medium">Status</th>
                        <th className="pb-3 pr-4 font-medium text-right">Raw</th>
                        <th className="pb-3 pr-6 font-medium text-right">Final</th>
                        <th className="pb-3 pr-4 font-medium">Sources OK</th>
                        <th className="pb-3 font-medium">Failed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.last_runs.map((run) => (
                        <tr key={run.id} className="border-b border-border/50 hover:bg-card/50 transition-colors">
                          <td className="py-2 text-xs text-muted">{run.id}</td>
                          <td className="py-2 text-xs">{formatDate(run.started_at)}</td>
                          <td className="py-2 text-xs">{run.finished_at ? formatDate(run.finished_at) : "—"}</td>
                          <td className="py-2">{statusBadge(run.status)}</td>
                          <td className="py-2 pr-4 text-xs text-right">{run.total_raw_devices}</td>
                          <td className="py-2 pr-6 text-xs text-right font-semibold">{run.final_count}</td>
                          <td className="py-2 pr-4 text-xs text-emerald-500">{(run.sources_ok || []).join(", ")}</td>
                          <td className="py-2 text-xs text-red-500">{(run.sources_failed || []).length > 0 ? (run.sources_failed || []).join(", ") : "—"}</td>
                        </tr>
                      ))}
                      {data.last_runs.length === 0 && (
                        <tr><td colSpan={8} className="py-4 text-center text-muted">No sync runs yet</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
