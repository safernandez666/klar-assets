import { useCallback, useEffect, useRef, useState } from "react";
import { jsPDF } from "jspdf";
import { KLAR_LOGO_WHITE } from "../assets/klar-logo-white";
import { Layout } from "../components/layout";
import { Sidebar } from "../components/sidebar";
import { StatusCards } from "../components/status-cards";
import { StatusHistory } from "../components/status-history";
import { PieCharts } from "../components/pie-charts";
import { RiskGauge } from "../components/risk-gauge";
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
      const pw = pdf.internal.pageSize.getWidth();
      const ph = pdf.internal.pageSize.getHeight();
      const m = 15; // margin
      const cw = pw - m * 2;
      let y = 0;

      // ── Colors — Klar brand: black base ────────────────────────────
      const colors: Record<string, [number, number, number]> = {
        FULLY_MANAGED: [16, 185, 129], MANAGED: [40, 40, 40],
        NO_EDR: [239, 68, 68], NO_MDM: [245, 158, 11],
        IDP_ONLY: [249, 115, 22], STALE: [160, 160, 160],
        SERVER: [100, 80, 160],
        crowdstrike: [50, 50, 50], jumpcloud: [90, 90, 90], okta: [140, 140, 140],
      };

      // ── Helpers ─────────────────────────────────────────────────────
      const checkPage = (need: number) => { if (y + need > ph - 15) { pdf.addPage(); y = 20; } };

      const h1 = (text: string) => {
        checkPage(18); y += 10;
        pdf.setFontSize(18); pdf.setFont("helvetica", "bold"); pdf.setTextColor(25, 25, 25);
        pdf.text(text, m, y); y += 2;
        pdf.setDrawColor(30, 30, 30); pdf.setLineWidth(0.8); pdf.line(m, y, m + cw, y);
        pdf.setLineWidth(0.2); y += 8;
      };

      const body = () => { pdf.setFont("helvetica", "normal"); pdf.setFontSize(10); pdf.setTextColor(60, 60, 60); };
      const bold = () => { pdf.setFont("helvetica", "bold"); pdf.setTextColor(30, 30, 30); };

      const richPara = (text: string) => {
        // Render text with **bold** sections
        body();
        const parts = text.split(/(\*\*[^*]+\*\*)/g);
        let lineX = m;
        const lineH = 5;
        for (const part of parts) {
          const isBold = part.startsWith("**") && part.endsWith("**");
          const clean = isBold ? part.slice(2, -2) : part;
          if (!clean) continue;
          if (isBold) bold(); else body();
          const w = pdf.getTextWidth(clean);
          if (lineX + w > m + cw) {
            y += lineH; lineX = m; checkPage(lineH);
          }
          pdf.text(clean, lineX, y);
          lineX += w;
        }
        y += lineH;
      };

      const bullet = (text: string) => {
        checkPage(6);
        pdf.setFontSize(10);
        const parts = text.split(/(\*\*[^*]+\*\*)/g);
        pdf.text("•", m + 2, y);
        let lineX = m + 7;
        for (const part of parts) {
          const isBold = part.startsWith("**") && part.endsWith("**");
          const clean = isBold ? part.slice(2, -2) : part;
          if (!clean) continue;
          if (isBold) bold(); else body();
          const words = clean.split(" ");
          for (const word of words) {
            const ww = pdf.getTextWidth(word + " ");
            if (lineX + ww > m + cw) { y += 5; lineX = m + 7; checkPage(5); }
            pdf.text(word + " ", lineX, y);
            lineX += ww;
          }
        }
        y += 5; body();
      };

      const tableRow = (cols: string[], widths: number[], isBold = false, bgColor?: [number, number, number]) => {
        checkPage(7);
        if (bgColor) {
          pdf.setFillColor(...bgColor); pdf.rect(m, y - 3.5, cw, 5.5, "F");
        }
        pdf.setFont("helvetica", isBold ? "bold" : "normal");
        pdf.setFontSize(8); pdf.setTextColor(isBold ? 255 : 50, isBold ? 255 : 50, isBold ? 255 : 50);
        let x = m + 1;
        cols.forEach((col, i) => {
          const max = Math.floor(widths[i] / 1.8);
          pdf.text(col.length > max ? col.slice(0, max) + "…" : col, x, y);
          x += widths[i];
        });
        y += 5;
      };

      const deviceTable = (devices: any[], showReason = false) => {
        const widths = showReason ? [38, 28, 42, 22, 50] : [42, 32, 48, 23, 35];
        const headers = showReason
          ? ["Hostname", "OS", "Owner", "Score", "Match Reason"]
          : ["Hostname", "Serial", "Owner", "OS", "Sources"];
        tableRow(headers, widths, true, [25, 25, 25]);
        for (const d of devices) {
          if (showReason) {
            tableRow([d.hostname || "N/A", d.os || "N/A", d.owner || "N/A",
              String(d.confidence?.toFixed(2) ?? "0"), d.match_reason || "N/A"], widths);
          } else {
            tableRow([d.hostname || "N/A", d.serial || "N/A", d.owner || "N/A",
              d.os || "N/A", (d.sources || []).join(", ")], widths);
          }
        }
      };

      // ── Horizontal bar chart ─────────────────────────────────────────
      const barChart = (data: { label: string; value: number; color: [number, number, number] }[], title: string) => {
        checkPage(10 + data.length * 9);
        pdf.setFontSize(10); pdf.setFont("helvetica", "bold"); pdf.setTextColor(50, 50, 50);
        pdf.text(title, m, y); y += 6;
        const maxVal = Math.max(...data.map(d => d.value), 1);
        const barMaxW = cw - 55;
        for (const d of data) {
          checkPage(9);
          pdf.setFontSize(8); pdf.setFont("helvetica", "normal"); pdf.setTextColor(80, 80, 80);
          pdf.text(d.label, m, y);
          const barW = (d.value / maxVal) * barMaxW;
          pdf.setFillColor(...d.color);
          pdf.roundedRect(m + 40, y - 3, barW, 4.5, 1, 1, "F");
          pdf.setFont("helvetica", "bold"); pdf.setTextColor(40, 40, 40);
          pdf.text(String(d.value), m + 42 + barW, y);
          y += 7;
        }
        y += 3;
      };

      // ── Donut-like pie chart ─────────────────────────────────────────
      const pieChart = (data: { label: string; value: number; color: [number, number, number] }[], cx: number, cy: number, r: number) => {
        const total = data.reduce((s, d) => s + d.value, 0);
        if (total === 0) return;
        let startAngle = -Math.PI / 2;
        for (const d of data) {
          const sweep = (d.value / total) * Math.PI * 2;
          const endAngle = startAngle + sweep;
          // Draw arc as filled triangle fan
          pdf.setFillColor(...d.color);
          const steps = Math.max(Math.ceil(sweep / 0.1), 2);
          const points: number[][] = [[cx, cy]];
          for (let i = 0; i <= steps; i++) {
            const a = startAngle + (sweep * i) / steps;
            points.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
          }
          // Draw as polygon
          for (let i = 1; i < points.length - 1; i++) {
            pdf.triangle(
              points[0][0], points[0][1],
              points[i][0], points[i][1],
              points[i + 1][0], points[i + 1][1], "F"
            );
          }
          startAngle = endAngle;
        }
        // Inner circle for donut effect
        pdf.setFillColor(255, 255, 255);
        const innerR = r * 0.55;
        const innerSteps = 36;
        for (let i = 0; i < innerSteps; i++) {
          const a1 = (Math.PI * 2 * i) / innerSteps;
          const a2 = (Math.PI * 2 * (i + 1)) / innerSteps;
          pdf.triangle(cx, cy, cx + innerR * Math.cos(a1), cy + innerR * Math.sin(a1),
            cx + innerR * Math.cos(a2), cy + innerR * Math.sin(a2), "F");
        }
      };

      // ════════════════════════════════════════════════════════════════
      // PAGE 1: Title + Charts + Executive Summary
      // ════════════════════════════════════════════════════════════════
      y = 20;
      pdf.setFillColor(15, 15, 15); pdf.rect(0, 0, pw, 48, "F");
      // Logo — 2:1 aspect ratio
      try { pdf.addImage(KLAR_LOGO_WHITE, "PNG", m, 7, 24, 12); } catch { /* skip if fails */ }
      pdf.setFontSize(20); pdf.setFont("helvetica", "bold"); pdf.setTextColor(255, 255, 255);
      pdf.text("Device Inventory Report", m + 28, 17);
      pdf.setFontSize(10); pdf.setFont("helvetica", "normal"); pdf.setTextColor(180, 180, 180);
      pdf.text(`Generated: ${new Date(report.generated_at).toLocaleString()}`, m, 30);
      const total = report.summary?.total || 0;
      const byStatus = report.summary?.by_status || {};
      const managed = (byStatus.MANAGED || 0) + (byStatus.FULLY_MANAGED || 0);
      const pct = total > 0 ? Math.round((managed / total) * 100) : 0;
      pdf.text(`Fleet: ${total} devices  |  ${pct}% managed  |  ${managed} covered`, m, 37);
      pdf.setFontSize(8); pdf.setTextColor(120, 120, 120);
      pdf.text("Klar — IT Security Team", m, 43);
      y = 55;

      // Status bar chart
      const statusData = [
        { label: "Fully Managed", value: byStatus.FULLY_MANAGED || 0, color: colors.FULLY_MANAGED },
        { label: "Managed", value: byStatus.MANAGED || 0, color: colors.MANAGED },
        { label: "No EDR", value: byStatus.NO_EDR || 0, color: colors.NO_EDR },
        { label: "No MDM", value: byStatus.NO_MDM || 0, color: colors.NO_MDM },
        { label: "IDP Only", value: byStatus.IDP_ONLY || 0, color: colors.IDP_ONLY },
        { label: "Stale", value: byStatus.STALE || 0, color: colors.STALE },
      ];
      barChart(statusData, "Status Distribution");

      // Pie chart + legend
      const pieData = statusData.filter(d => d.value > 0);
      pieChart(pieData, m + 25, y + 20, 18);
      // Legend next to pie
      let ly = y + 6;
      pdf.setFontSize(8);
      for (const d of pieData) {
        pdf.setFillColor(...d.color); pdf.rect(m + 50, ly - 2.5, 3, 3, "F");
        pdf.setFont("helvetica", "normal"); pdf.setTextColor(60, 60, 60);
        pdf.text(`${d.label}: ${d.value} (${total > 0 ? Math.round((d.value / total) * 100) : 0}%)`, m + 55, ly);
        ly += 5;
      }
      y = Math.max(y + 45, ly + 5);

      // Source bar chart
      const bySource = report.summary?.by_source || {};
      const srcData = Object.entries(bySource).map(([k, v]) => ({
        label: k, value: v as number, color: colors[k] || [100, 100, 100] as [number, number, number],
      }));
      barChart(srcData, "Source Coverage (raw devices)");

      // Status reference
      checkPage(60);
      y += 4;
      pdf.setFontSize(10); pdf.setFont("helvetica", "bold"); pdf.setTextColor(30, 30, 30);
      pdf.text("Status Reference", m, y); y += 2;
      pdf.setDrawColor(200); pdf.line(m, y, m + cw, y); y += 5;

      const statusRef = [
        { label: "Fully Managed", color: colors.FULLY_MANAGED, desc: "JumpCloud (MDM) + CrowdStrike (EDR) + Okta (IDP) + owner assigned. Complete visibility." },
        { label: "Managed", color: colors.MANAGED, desc: "JumpCloud (MDM) + CrowdStrike (EDR). Device is managed and protected — the baseline." },
        { label: "No EDR", color: colors.NO_EDR, desc: "In JumpCloud but missing CrowdStrike. Managed by IT but without endpoint protection." },
        { label: "No MDM", color: colors.NO_MDM, desc: "In CrowdStrike but missing JumpCloud. Has EDR but IT doesn't manage it." },
        { label: "IDP Only", color: colors.IDP_ONLY, desc: "Only in Okta, no EDR or MDM. Potential shadow IT — needs investigation." },
        { label: "Server/VM", color: colors.SERVER || [100, 80, 160], desc: "Servers and VMs with CrowdStrike. Don't require JumpCloud (MDM) enrollment." },
        { label: "Stale", color: colors.STALE, desc: "Not seen in 90+ days. Candidate for cleanup to reduce license costs." },
      ];
      for (const ref of statusRef) {
        checkPage(12);
        pdf.setFillColor(...ref.color); pdf.roundedRect(m, y - 3, 3, 3, 0.5, 0.5, "F");
        pdf.setFontSize(8); pdf.setFont("helvetica", "bold"); pdf.setTextColor(30, 30, 30);
        pdf.text(ref.label, m + 5, y);
        pdf.setFont("helvetica", "normal"); pdf.setTextColor(80, 80, 80);
        const descLines = pdf.splitTextToSize(ref.desc, cw - 35);
        pdf.text(descLines, m + 35, y);
        y += Math.max(descLines.length * 4, 5) + 2;
      }

      // ════════════════════════════════════════════════════════════════
      // PAGE 2: Executive Summary (AI)
      // ════════════════════════════════════════════════════════════════
      pdf.addPage(); y = 20;
      const summaryLines = (report.executive_summary || "").split("\n");
      for (const line of summaryLines) {
        if (line.startsWith("## ")) {
          h1(line.replace("## ", ""));
        } else if (line.startsWith("- ")) {
          bullet(line.replace("- ", ""));
        } else if (line.trim()) {
          richPara(line);
        } else {
          y += 3;
        }
      }

      // ════════════════════════════════════════════════════════════════
      // PAGE 3: Quick Actions
      // ════════════════════════════════════════════════════════════════
      pdf.addPage(); y = 20;
      h1("Quick Actions");
      body();
      richPara("Prioritized actions to improve fleet security posture. Address **critical** and **high** items first.");
      y += 3;

      const prioColors: Record<string, [number, number, number]> = {
        critical: [220, 38, 38], high: [217, 119, 6], medium: [59, 130, 246],
        low: [107, 114, 128], success: [16, 185, 129], info: [59, 130, 246],
      };
      const prioLabels: Record<string, string> = {
        critical: "CRITICAL", high: "HIGH", medium: "MEDIUM", low: "LOW", success: "OK", info: "INFO",
      };

      for (const action of report.actions || []) {
        checkPage(20);
        const pc = prioColors[action.priority] || [100, 100, 100];
        // Priority badge
        pdf.setFillColor(...pc); pdf.roundedRect(m, y - 3, 18, 5, 1, 1, "F");
        pdf.setFontSize(7); pdf.setFont("helvetica", "bold"); pdf.setTextColor(255, 255, 255);
        pdf.text(prioLabels[action.priority] || "INFO", m + 1.5, y);
        // Title
        pdf.setFontSize(10); pdf.setFont("helvetica", "bold"); pdf.setTextColor(30, 30, 30);
        pdf.text(action.title, m + 21, y);
        y += 5;
        // Description
        body(); pdf.setFontSize(9);
        const descLines = pdf.splitTextToSize(action.description, cw - 5);
        checkPage(descLines.length * 4);
        pdf.text(descLines, m + 3, y);
        y += descLines.length * 4 + 5;
      }

      // ════════════════════════════════════════════════════════════════
      // Category pages: Devices to act on
      // ════════════════════════════════════════════════════════════════
      const cats = report.categories || {};
      for (const [, cat] of Object.entries(cats) as [string, any][]) {
        if (cat.count === 0) continue;
        pdf.addPage(); y = 20;
        h1(`${cat.title} (${cat.count})`);
        if (cat.devices?.length > 0) {
          deviceTable(cat.devices);
        }
        if (cat.count > (cat.devices?.length || 0)) {
          y += 3; pdf.setFontSize(8); pdf.setTextColor(130, 130, 130);
          pdf.text(`... and ${cat.count - cat.devices.length} more devices`, m, y); y += 5;
        }
      }

      // ════════════════════════════════════════════════════════════════
      // Cross-source matches
      // ════════════════════════════════════════════════════════════════
      if (report.unique_matches?.devices?.length > 0) {
        pdf.addPage(); y = 20;
        h1(`${report.unique_matches.title} (${report.unique_matches.count})`);
        richPara("Devices identified across **multiple sources** and correlated into a single record. The **match reason** and **confidence score** explain how the correlation was made.");
        y += 4;
        deviceTable(report.unique_matches.devices, true);
      }

      // ════════════════════════════════════════════════════════════════
      // Low confidence
      // ════════════════════════════════════════════════════════════════
      if (report.low_confidence?.devices?.length > 0) {
        pdf.addPage(); y = 20;
        h1(`${report.low_confidence.title} (${report.low_confidence.count})`);
        richPara("Devices with confidence below **0.5**. May be incorrectly matched or single-source records. Review **serial numbers** and **hostnames** to improve data quality.");
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
        onSync={handleSync}
        syncing={syncing}
        onExportPdf={handleExportPdf}
        exporting={exporting}
      />
      <div className="pl-14">
        <Layout lastSync={lastSync}>
          <div ref={contentRef} className="space-y-8">
            <StatusCards summary={summary} trends={trends} />
            <RiskGauge summary={summary} />
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
