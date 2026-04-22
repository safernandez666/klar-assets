import { useCallback, useEffect, useRef, useState } from "react";
import { jsPDF } from "jspdf";
import { Layout } from "../components/layout";
import { Sidebar } from "../components/sidebar";
import { StatusCards } from "../components/status-cards";
import { StatusHistory } from "../components/status-history";
import { PieCharts } from "../components/pie-charts";
import { QualityMetrics } from "../components/quality-metrics";
import { SourcesHealth } from "../components/sources-health";
import { DeviceInventory } from "../components/device-inventory";
import { LowConfidence } from "../components/low-confidence";
import { api } from "../lib/api";
import type { Device, Insight, StatusSnapshot, Summary, SyncRun, TrendsResponse } from "../types";

export default function Dashboard() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [lastSync, setLastSync] = useState<SyncRun | null>(null);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [history, setHistory] = useState<StatusSnapshot[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [refreshingInsights, setRefreshingInsights] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, lastSyncRes, devicesRes, trendsRes, historyRes, insightsRes] = await Promise.all([
        api.getSummary(),
        api.getLastSync(),
        api.getDevices(),
        api.getTrends(),
        api.getHistory(),
        api.getInsights(),
      ]);
      setSummary(summaryRes);
      setLastSync(lastSyncRes.last_sync);
      setDevices(devicesRes.devices || []);
      setTrends(trendsRes);
      setHistory(historyRes.history || []);
      setInsights(insightsRes.actions || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      await api.triggerSync();
      setTimeout(async () => {
        await loadData();
        setSyncing(false);
      }, 4000);
    } catch (e) {
      console.error(e);
      setSyncing(false);
    }
  }, [loadData]);

  const handleRefreshInsights = useCallback(async () => {
    setRefreshingInsights(true);
    try {
      const res = await api.getInsights();
      setInsights(res.actions || []);
    } catch (e) {
      console.error(e);
    } finally {
      setRefreshingInsights(false);
    }
  }, []);

  const handleExportPdf = useCallback(async () => {
    setExporting(true);
    try {
      const report = await api.getFullReport();

      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 15;
      const cw = pageWidth - margin * 2; // content width
      let y = 0;

      // ── Helpers ──────────────────────────────────────────────────────
      const checkPage = (needed: number) => {
        if (y + needed > pageHeight - 15) { pdf.addPage(); y = 20; }
      };
      const heading = (text: string, size = 14) => {
        checkPage(15);
        y += 8;
        pdf.setFontSize(size);
        pdf.setFont("helvetica", "bold");
        pdf.setTextColor(40);
        pdf.text(text, margin, y);
        y += 2;
        pdf.setDrawColor(200);
        pdf.line(margin, y, margin + cw, y);
        y += 6;
        pdf.setFont("helvetica", "normal");
        pdf.setFontSize(10);
        pdf.setTextColor(60);
      };
      const para = (text: string) => {
        const lines = pdf.splitTextToSize(text.replace(/\*\*/g, ""), cw);
        checkPage(lines.length * 5);
        pdf.text(lines, margin, y);
        y += lines.length * 5;
      };
      const bullet = (text: string) => {
        const lines = pdf.splitTextToSize(text.replace(/\*\*/g, ""), cw - 6);
        checkPage(lines.length * 5);
        pdf.text("•", margin + 1, y);
        pdf.text(lines, margin + 6, y);
        y += lines.length * 5;
      };
      const tableRow = (cols: string[], widths: number[], bold = false) => {
        checkPage(6);
        pdf.setFont("helvetica", bold ? "bold" : "normal");
        pdf.setFontSize(8);
        let x = margin;
        cols.forEach((col, i) => {
          const truncated = col.length > Math.floor(widths[i] / 2) ? col.slice(0, Math.floor(widths[i] / 2)) + "…" : col;
          pdf.text(truncated, x, y);
          x += widths[i];
        });
        y += 5;
      };
      const deviceTable = (devices: any[], showReason = false) => {
        const widths = showReason
          ? [40, 30, 45, 25, 40]
          : [45, 35, 50, 25, 25];
        const headers = showReason
          ? ["Hostname", "OS", "Owner", "Score", "Match Reason"]
          : ["Hostname", "Serial", "Owner", "OS", "Sources"];
        tableRow(headers, widths, true);
        y += 1;
        pdf.setDrawColor(220);
        pdf.line(margin, y - 1, margin + cw, y - 1);
        y += 1;
        for (const d of devices) {
          if (showReason) {
            tableRow([
              d.hostname || "N/A",
              d.os || "N/A",
              d.owner || "N/A",
              String(d.confidence?.toFixed(2) ?? "0"),
              d.match_reason || "N/A",
            ], widths);
          } else {
            tableRow([
              d.hostname || "N/A",
              d.serial || "N/A",
              d.owner || "N/A",
              d.os || "N/A",
              (d.sources || []).join(", "),
            ], widths);
          }
        }
      };

      // ── Page 1: Title + Executive Summary ────────────────────────────
      y = 25;
      pdf.setFontSize(22);
      pdf.setFont("helvetica", "bold");
      pdf.setTextColor(30);
      pdf.text("Device Inventory Report", margin, y);
      y += 8;
      pdf.setFontSize(10);
      pdf.setFont("helvetica", "normal");
      pdf.setTextColor(130);
      pdf.text(`Generated: ${new Date(report.generated_at).toLocaleString()}`, margin, y);
      const total = report.summary?.total || 0;
      pdf.text(`Fleet size: ${total} desktop/laptop devices`, margin + 90, y);
      y += 12;

      // Executive summary from AI
      pdf.setTextColor(60);
      const summaryLines = (report.executive_summary || "").split("\n");
      for (const line of summaryLines) {
        if (line.startsWith("## ")) {
          heading(line.replace("## ", ""), 13);
        } else if (line.startsWith("- ")) {
          bullet(line.replace("- ", ""));
        } else if (line.trim()) {
          para(line);
        } else {
          y += 3;
        }
      }

      // ── Page 2: Quick Actions ────────────────────────────────────────
      pdf.addPage(); y = 20;
      heading("Quick Actions", 16);
      const priorityLabels: Record<string, string> = {
        critical: "CRITICAL", high: "HIGH", medium: "MEDIUM", low: "LOW", success: "OK", info: "INFO",
      };
      for (const action of report.actions || []) {
        checkPage(15);
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(9);
        pdf.setTextColor(
          action.priority === "critical" ? 200 : action.priority === "high" ? 180 : 80,
          action.priority === "critical" ? 50 : action.priority === "high" ? 120 : 80,
          action.priority === "critical" ? 50 : action.priority === "high" ? 20 : 80,
        );
        pdf.text(`[${priorityLabels[action.priority] || "INFO"}]`, margin, y);
        pdf.setTextColor(40);
        pdf.text(action.title, margin + 22, y);
        y += 5;
        pdf.setFont("helvetica", "normal");
        pdf.setFontSize(8);
        pdf.setTextColor(100);
        const descLines = pdf.splitTextToSize(action.description, cw - 5);
        pdf.text(descLines, margin + 5, y);
        y += descLines.length * 4 + 4;
      }

      // ── Devices without EDR ──────────────────────────────────────────
      const cats = report.categories || {};
      for (const [, cat] of Object.entries(cats) as [string, any][]) {
        if (cat.count === 0) continue;
        pdf.addPage(); y = 20;
        heading(`${cat.title} (${cat.count})`, 14);
        if (cat.devices?.length > 0) {
          deviceTable(cat.devices);
        }
        if (cat.count > cat.devices?.length) {
          y += 3;
          pdf.setFontSize(8);
          pdf.setTextColor(130);
          pdf.text(`... and ${cat.count - cat.devices.length} more`, margin, y);
          y += 5;
        }
      }

      // ── Cross-source Matched Devices ─────────────────────────────────
      if (report.unique_matches?.devices?.length > 0) {
        pdf.addPage(); y = 20;
        heading(`${report.unique_matches.title} (${report.unique_matches.count})`, 14);
        para("These devices were identified across multiple sources and correlated into a single record. The match reason and confidence score indicate how the correlation was made.");
        y += 4;
        deviceTable(report.unique_matches.devices, true);
      }

      // ── Low Confidence Matches ───────────────────────────────────────
      if (report.low_confidence?.devices?.length > 0) {
        pdf.addPage(); y = 20;
        heading(`${report.low_confidence.title} (${report.low_confidence.count})`, 14);
        para("These devices have a confidence score below 0.5. They may be incorrectly matched or represent single-source records that could not be correlated. Review serial numbers and hostnames.");
        y += 4;
        deviceTable(report.low_confidence.devices, true);
      }

      pdf.save("device-inventory-report.pdf");
    } catch (e) {
      console.error("PDF export failed:", e);
    } finally {
      setExporting(false);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-foreground">
        <div className="flex items-center gap-3">
          <svg className="h-5 w-5 animate-spin text-accent" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span className="text-sm text-muted">Loading dashboard...</span>
        </div>
      </div>
    );
  }

  return (
    <>
      <Sidebar
        insights={insights}
        onRefreshInsights={handleRefreshInsights}
        refreshing={refreshingInsights}
      />
      <div className="pl-14">
        <Layout
          lastSync={lastSync}
          onSync={handleSync}
          syncing={syncing}
          onExportPdf={handleExportPdf}
          exporting={exporting}
        >
          <div ref={contentRef} className="space-y-8">
            <StatusCards summary={summary} trends={trends} />
            {history.length > 1 && <StatusHistory history={history} />}
            <PieCharts summary={summary} />
            <QualityMetrics devices={devices} lastSync={lastSync} />
            <SourcesHealth summary={summary} lastSync={lastSync} />
            <DeviceInventory devices={devices} />
            <LowConfidence devices={devices} />
          </div>
        </Layout>
      </div>
    </>
  );
}
