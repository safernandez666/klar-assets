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

  const loadData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      // Fast: load core data first (summary, sync, devices)
      const [summaryRes, lastSyncRes, devicesRes] = await Promise.all([
        api.getSummary(),
        api.getLastSync(),
        api.getDevices(),
      ]);
      setSummary(summaryRes);
      setLastSync(lastSyncRes.last_sync);
      setDevices(devicesRes.devices || []);
      setLoading(false);

      // Slow: load secondary data in background (trends, history, insights)
      const [trendsRes, historyRes, insightsRes] = await Promise.all([
        api.getTrends(),
        api.getHistory(),
        api.getInsights(),
      ]);
      setTrends(trendsRes);
      setHistory(historyRes.history || []);
      setInsights(insightsRes.actions || []);
    } catch (e) {
      console.error(e);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(true);
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
      const m = 18;
      const cw = pw - m * 2;
      let y = 0;
      let pageNum = 0;

      // ── Brand palette ──────────────────────────────────────────────
      type C3 = [number, number, number];
      const K = { black: [15, 15, 15] as C3, dark: [35, 35, 35] as C3, mid: [100, 100, 100] as C3, light: [180, 180, 180] as C3, bg: [245, 245, 243] as C3, white: [255, 255, 255] as C3 };
      const status: Record<string, C3> = {
        FULLY_MANAGED: [16, 185, 129], MANAGED: [45, 45, 45], NO_EDR: [220, 50, 50],
        NO_MDM: [230, 145, 20], IDP_ONLY: [230, 100, 25], STALE: [160, 160, 160], SERVER: [95, 75, 155],
      };
      const srcColors: Record<string, C3> = { crowdstrike: [45, 45, 45], jumpcloud: [80, 80, 80], okta: [130, 130, 130] };

      // ── Helpers ────────────────────────────────────────────────────
      const newPage = () => { if (pageNum > 0) pdf.addPage(); pageNum++; y = 20; };
      const check = (need: number) => { if (y + need > ph - 18) { newPage(); } };

      const footer = () => {
        pdf.setFontSize(7); pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.light);
        pdf.text("Klar Device Normalizer", m, ph - 8);
        pdf.text(`Page ${pageNum}`, pw - m, ph - 8, { align: "right" });
        pdf.setDrawColor(230, 230, 230); pdf.setLineWidth(0.3); pdf.line(m, ph - 12, pw - m, ph - 12);
      };

      const sectionTitle = (text: string) => {
        check(16); y += 8;
        pdf.setFillColor(...K.black); pdf.rect(m, y - 5, 1.5, 7, "F");
        pdf.setFontSize(14); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...K.black);
        pdf.text(text, m + 5, y); y += 8;
      };

      const subTitle = (text: string) => {
        check(10); y += 4;
        pdf.setFontSize(10); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...K.dark);
        pdf.text(text, m, y); y += 5;
      };

      const bodyText = () => { pdf.setFont("helvetica", "normal"); pdf.setFontSize(9.5); pdf.setTextColor(55, 55, 55); };

      const richLine = (text: string) => {
        bodyText();
        const parts = text.split(/(\*\*[^*]+\*\*)/g);
        let lx = m;
        for (const part of parts) {
          const isBold = part.startsWith("**") && part.endsWith("**");
          const clean = isBold ? part.slice(2, -2) : part;
          if (!clean) continue;
          pdf.setFont("helvetica", isBold ? "bold" : "normal");
          pdf.setTextColor(isBold ? 20 : 55, isBold ? 20 : 55, isBold ? 20 : 55);
          const words = clean.split(" ");
          for (const w of words) {
            const ww = pdf.getTextWidth(w + " ");
            if (lx + ww > m + cw) { y += 4.5; lx = m; check(5); }
            pdf.text(w + " ", lx, y); lx += ww;
          }
        }
        y += 5;
      };

      const bulletPoint = (text: string) => {
        check(6);
        pdf.setFillColor(...K.dark); pdf.rect(m + 2, y - 1.2, 1.2, 1.2, "F");
        const shifted = text;
        pdf.setFont("helvetica", "normal"); pdf.setFontSize(9); pdf.setTextColor(55, 55, 55);
        // Render with bold
        const parts = shifted.split(/(\*\*[^*]+\*\*)/g);
        let lx = m + 7;
        for (const part of parts) {
          const isBold = part.startsWith("**") && part.endsWith("**");
          const clean = isBold ? part.slice(2, -2) : part;
          if (!clean) continue;
          pdf.setFont("helvetica", isBold ? "bold" : "normal");
          pdf.setTextColor(isBold ? 20 : 55, isBold ? 20 : 55, isBold ? 20 : 55);
          const words = clean.split(" ");
          for (const w of words) {
            const ww = pdf.getTextWidth(w + " ");
            if (lx + ww > m + cw) { y += 4.2; lx = m + 7; check(5); }
            pdf.text(w + " ", lx, y); lx += ww;
          }
        }
        y += 5;
      };

      const tblRow = (cols: string[], widths: number[], isHeader = false, stripe = false) => {
        check(6);
        if (isHeader) {
          pdf.setFillColor(...K.black); pdf.rect(m, y - 3.5, cw, 5.5, "F");
          pdf.setFont("helvetica", "bold"); pdf.setFontSize(7.5); pdf.setTextColor(255, 255, 255);
        } else {
          if (stripe) { pdf.setFillColor(...K.bg); pdf.rect(m, y - 3.5, cw, 5.5, "F"); }
          pdf.setFont("helvetica", "normal"); pdf.setFontSize(7.5); pdf.setTextColor(50, 50, 50);
        }
        let x = m + 2;
        cols.forEach((c, i) => {
          const mx = Math.floor(widths[i] / 1.7);
          pdf.text(c.length > mx ? c.slice(0, mx) + "…" : c, x, y);
          x += widths[i];
        });
        y += 5;
      };

      const devTable = (devices: any[], showReason = false) => {
        const W = showReason ? [38, 26, 42, 18, 56] : [42, 30, 48, 22, 38];
        const H = showReason ? ["Hostname", "OS", "Owner", "Score", "Match Reason"] : ["Hostname", "Serial", "Owner", "OS", "Sources"];
        tblRow(H, W, true);
        devices.forEach((d, i) => {
          if (showReason) tblRow([d.hostname||"—",d.os||"—",d.owner||"—",String(d.confidence?.toFixed(2)??"0"),d.match_reason||"—"], W, false, i%2===0);
          else tblRow([d.hostname||"—",d.serial||"—",d.owner||"—",d.os||"—",(d.sources||[]).join(", ")], W, false, i%2===0);
        });
      };

      const hBar = (data: {label:string;value:number;color:C3}[], title: string) => {
        check(10 + data.length * 8); subTitle(title);
        const mx = Math.max(...data.map(d=>d.value), 1);
        const bw = cw - 50;
        for (const d of data) {
          check(8);
          pdf.setFontSize(8); pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.mid);
          pdf.text(d.label, m, y);
          const w = (d.value / mx) * bw;
          // Bar bg
          pdf.setFillColor(235, 235, 233); pdf.roundedRect(m + 35, y - 2.8, bw, 4, 1.5, 1.5, "F");
          // Bar fill
          pdf.setFillColor(...d.color); pdf.roundedRect(m + 35, y - 2.8, w, 4, 1.5, 1.5, "F");
          pdf.setFont("helvetica", "bold"); pdf.setFontSize(8); pdf.setTextColor(...K.dark);
          pdf.text(String(d.value), m + 37 + bw, y);
          y += 7;
        }
        y += 2;
      };

      // ══════════════════════════════════════════════════════════════
      // COVER PAGE
      // ══════════════════════════════════════════════════════════════
      newPage();

      // Black header band
      pdf.setFillColor(...K.black); pdf.rect(0, 0, pw, 52, "F");
      // Logo
      try { pdf.addImage(KLAR_LOGO_WHITE, "PNG", m, 10, 22, 11); } catch { /* */ }
      // Title
      pdf.setFontSize(22); pdf.setFont("helvetica", "bold"); pdf.setTextColor(255, 255, 255);
      pdf.text("Device Inventory Report", m, 35);
      pdf.setFontSize(9); pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.light);
      pdf.text(`Generated ${new Date(report.generated_at).toLocaleString()}  —  IT Security Team`, m, 44);

      // Risk Score — right side, clean number
      const total = report.summary?.total || 0;
      const byStatus = report.summary?.by_status || {};
      const managed = (byStatus.MANAGED || 0) + (byStatus.FULLY_MANAGED || 0);
      const riskScore = report.summary?.risk_score ?? 0;
      const rsColor: C3 = riskScore >= 80 ? [16, 185, 129] : riskScore >= 60 ? [245, 158, 11] : riskScore >= 40 ? [249, 115, 22] : [239, 68, 68];
      const rsLabel = riskScore >= 85 ? "Excellent" : riskScore >= 70 ? "Good" : riskScore >= 55 ? "Fair" : riskScore >= 40 ? "At Risk" : "Critical";

      pdf.setFontSize(36); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...rsColor);
      pdf.text(String(riskScore), pw - m, 30, { align: "right" });
      pdf.setFontSize(9); pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.light);
      pdf.text(`Risk Score — ${rsLabel}`, pw - m, 38, { align: "right" });

      // KPI strip below header
      y = 58;
      const pct = total > 0 ? Math.round((managed / total) * 100) : 0;
      const kpis = [
        { label: "Total Fleet", value: String(total) },
        { label: "Managed", value: String(managed) },
        { label: "Coverage", value: `${pct}%` },
        { label: "Without EDR", value: String(byStatus.NO_EDR || 0) },
        { label: "Without MDM", value: String(byStatus.NO_MDM || 0) },
      ];
      const kpiW = cw / kpis.length;
      kpis.forEach((kpi, i) => {
        const x = m + i * kpiW;
        pdf.setFillColor(i === 0 ? 250 : 255, 250, i === 0 ? 245 : 255);
        pdf.setFontSize(18); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...K.black);
        pdf.text(kpi.value, x + kpiW / 2, y + 2, { align: "center" });
        pdf.setFontSize(7); pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.mid);
        pdf.text(kpi.label, x + kpiW / 2, y + 8, { align: "center" });
      });
      y += 16;

      // Thin divider
      pdf.setDrawColor(220, 220, 218); pdf.setLineWidth(0.3); pdf.line(m, y, pw - m, y); y += 6;

      // Status bar chart
      const statusData = Object.entries({ "Fully Managed": "FULLY_MANAGED", Managed: "MANAGED", "No EDR": "NO_EDR", "No MDM": "NO_MDM", "IDP Only": "IDP_ONLY", "Server/VM": "SERVER", Stale: "STALE" })
        .map(([label, key]) => ({ label, value: byStatus[key] || 0, color: status[key] || K.mid }))
        .filter(d => d.value > 0);
      hBar(statusData, "Status Distribution");

      // Source bar chart
      const bySource = report.summary?.by_source || {};
      const srcData = Object.entries(bySource).map(([k, v]) => ({ label: k, value: v as number, color: srcColors[k] || K.mid }));
      hBar(srcData, "Source Coverage");

      // Status reference
      check(55); y += 2;
      subTitle("Status Definitions");
      const refs = [
        { k: "FULLY_MANAGED", l: "Fully Managed", d: "MDM + EDR + IDP + owner. Complete visibility." },
        { k: "MANAGED", l: "Managed", d: "MDM + EDR. The operational baseline." },
        { k: "NO_EDR", l: "No EDR", d: "In MDM but missing CrowdStrike. Needs EDR deployment." },
        { k: "NO_MDM", l: "No MDM", d: "Has EDR but not enrolled in JumpCloud." },
        { k: "IDP_ONLY", l: "IDP Only", d: "Only in Okta. Potential shadow IT." },
        { k: "SERVER", l: "Server/VM", d: "Infrastructure with EDR. Doesn't need MDM." },
        { k: "STALE", l: "Stale", d: "Inactive 90+ days. Cleanup candidate." },
      ];
      for (const r of refs) {
        check(7);
        pdf.setFillColor(...(status[r.k] || K.mid)); pdf.roundedRect(m, y - 2, 2.5, 2.5, 0.5, 0.5, "F");
        pdf.setFontSize(8); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...K.dark);
        pdf.text(r.l, m + 5, y);
        pdf.setFont("helvetica", "normal"); pdf.setTextColor(...K.mid);
        pdf.text(r.d, m + 32, y);
        y += 5;
      }

      footer();

      // ══════════════════════════════════════════════════════════════
      // PAGE 2: Executive Summary
      // ══════════════════════════════════════════════════════════════
      newPage();
      const lines = (report.executive_summary || "").split("\n");
      for (const line of lines) {
        if (line.startsWith("## ")) { sectionTitle(line.replace("## ", "")); }
        else if (line.startsWith("# ")) { sectionTitle(line.replace("# ", "")); }
        else if (line.startsWith("- ")) { bulletPoint(line.replace("- ", "")); }
        else if (line.trim()) { richLine(line); }
        else { y += 3; }
      }
      footer();

      // ══════════════════════════════════════════════════════════════
      // PAGE 3: Quick Actions
      // ══════════════════════════════════════════════════════════════
      newPage();
      sectionTitle("Quick Actions");
      bodyText();
      richLine("Prioritized actions to improve fleet security posture. Address **critical** and **high** items first.");
      y += 2;

      const pc: Record<string, C3> = { critical: [200, 30, 30], high: [210, 110, 0], medium: [50, 50, 50], low: [140, 140, 140], success: [16, 160, 110], info: [50, 50, 50] };
      const pl: Record<string, string> = { critical: "CRITICAL", high: "HIGH", medium: "MEDIUM", low: "LOW", success: "OK", info: "INFO" };

      for (const action of report.actions || []) {
        check(22);
        // Left accent bar
        const ac = pc[action.priority] || K.mid;
        pdf.setFillColor(...ac); pdf.rect(m, y - 4, 2, 14, "F");
        // Badge
        pdf.setFillColor(...ac); pdf.roundedRect(m + 5, y - 3.5, 16, 4.5, 1, 1, "F");
        pdf.setFontSize(6.5); pdf.setFont("helvetica", "bold"); pdf.setTextColor(255, 255, 255);
        pdf.text(pl[action.priority] || "INFO", m + 6, y - 0.5);
        // Title
        pdf.setFontSize(10); pdf.setFont("helvetica", "bold"); pdf.setTextColor(...K.black);
        pdf.text(action.title, m + 24, y);
        y += 5;
        // Description
        pdf.setFontSize(8.5); pdf.setFont("helvetica", "normal"); pdf.setTextColor(70, 70, 70);
        const dl = pdf.splitTextToSize(action.description, cw - 10);
        check(dl.length * 4); pdf.text(dl, m + 5, y);
        y += dl.length * 4 + 5;
      }
      footer();

      // ══════════════════════════════════════════════════════════════
      // Category pages
      // ══════════════════════════════════════════════════════════════
      const cats = report.categories || {};
      for (const [, cat] of Object.entries(cats) as [string, any][]) {
        if (cat.count === 0) continue;
        newPage();
        sectionTitle(`${cat.title} (${cat.count})`);
        if (cat.devices?.length > 0) devTable(cat.devices);
        if (cat.count > (cat.devices?.length || 0)) {
          y += 3; pdf.setFontSize(8); pdf.setTextColor(...K.light);
          pdf.text(`+ ${cat.count - cat.devices.length} more devices not shown`, m, y); y += 5;
        }
        footer();
      }

      // ══════════════════════════════════════════════════════════════
      // Cross-source matches
      // ══════════════════════════════════════════════════════════════
      if (report.unique_matches?.devices?.length > 0) {
        newPage();
        sectionTitle(`${report.unique_matches.title} (${report.unique_matches.count})`);
        richLine("Devices correlated across **multiple sources**. The **match reason** and **confidence score** show how each correlation was determined.");
        y += 3; devTable(report.unique_matches.devices, true);
        footer();
      }

      // ══════════════════════════════════════════════════════════════
      // Low confidence
      // ══════════════════════════════════════════════════════════════
      if (report.low_confidence?.devices?.length > 0) {
        newPage();
        sectionTitle(`${report.low_confidence.title} (${report.low_confidence.count})`);
        richLine("Devices with confidence below **0.5**. Review **serial numbers** and **hostnames** for potential mismatches.");
        y += 3; devTable(report.low_confidence.devices, true);
        footer();
      }

      pdf.save("klar-device-report.pdf");
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
