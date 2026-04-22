import { useCallback, useEffect, useRef, useState } from "react";
import html2canvas from "html2canvas";
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
    if (!contentRef.current) return;
    setExporting(true);
    try {
      // Fetch AI report text
      let reportText = "";
      try {
        const res = await api.getReport();
        reportText = res.report || "";
      } catch {
        reportText = "";
      }

      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const margin = 15;
      const contentWidth = pageWidth - margin * 2;

      // Title page with AI report
      pdf.setFontSize(20);
      pdf.setFont("helvetica", "bold");
      pdf.text("Device Inventory Report", margin, 25);

      pdf.setFontSize(10);
      pdf.setFont("helvetica", "normal");
      pdf.setTextColor(120);
      pdf.text(`Generated: ${new Date().toLocaleString()}`, margin, 33);
      pdf.setTextColor(0);

      if (reportText) {
        let y = 45;
        const lines = reportText.split("\n");
        for (const line of lines) {
          if (line.startsWith("## ")) {
            y += 4;
            pdf.setFontSize(13);
            pdf.setFont("helvetica", "bold");
            pdf.text(line.replace("## ", ""), margin, y);
            y += 8;
            pdf.setFontSize(10);
            pdf.setFont("helvetica", "normal");
          } else if (line.startsWith("- ")) {
            const clean = line.replace(/\*\*/g, "").replace("- ", "");
            const wrapped = pdf.splitTextToSize(`  •  ${clean}`, contentWidth - 5);
            pdf.text(wrapped, margin, y);
            y += wrapped.length * 5;
          } else if (line.trim()) {
            const wrapped = pdf.splitTextToSize(line.replace(/\*\*/g, ""), contentWidth);
            pdf.text(wrapped, margin, y);
            y += wrapped.length * 5;
          } else {
            y += 3;
          }
          if (y > 270) {
            pdf.addPage();
            y = 20;
          }
        }
      }

      // Dashboard screenshot pages
      pdf.addPage();
      pdf.setFontSize(14);
      pdf.setFont("helvetica", "bold");
      pdf.text("Dashboard Overview", margin, 20);

      const element = contentRef.current;
      const canvas = await html2canvas(element, {
        scale: 2,
        useCORS: true,
        backgroundColor: null,
      });
      const imgData = canvas.toDataURL("image/png");

      const pageHeight = pdf.internal.pageSize.getHeight();
      const imgWidth = contentWidth;
      const imgHeight = (canvas.height * imgWidth) / canvas.width;

      let heightLeft = imgHeight;
      let position = 28;

      pdf.addImage(imgData, "PNG", margin, position, imgWidth, imgHeight);
      heightLeft -= pageHeight - margin * 2;

      while (heightLeft > 0) {
        position = heightLeft - imgHeight + margin;
        pdf.addPage();
        pdf.addImage(imgData, "PNG", margin, position, imgWidth, imgHeight);
        heightLeft -= pageHeight - margin * 2;
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
