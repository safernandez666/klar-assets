import { motion } from "motion/react";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import type { Summary } from "../types";

interface RiskGaugeProps {
  summary: Summary | null;
}

function getScoreColor(score: number): string {
  if (score >= 80) return "#10b981";
  if (score >= 60) return "#f59e0b";
  if (score >= 40) return "#f97316";
  return "#ef4444";
}

function getScoreLabel(score: number): string {
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Good";
  if (score >= 55) return "Fair";
  if (score >= 40) return "At Risk";
  return "Critical";
}

export function RiskGauge({ summary }: RiskGaugeProps) {
  const score = summary?.risk_score ?? 0;
  const color = getScoreColor(score);
  const label = getScoreLabel(score);

  // SVG semicircle gauge
  const cx = 100;
  const cy = 90;
  const r = 72;
  const strokeW = 12;
  // Arc from 180° to 0° (left to right, semicircle)
  const startAngle = Math.PI;
  const endAngle = 0;
  const totalAngle = startAngle - endAngle;
  const filledAngle = startAngle - (score / 100) * totalAngle;

  const arcPath = (angle1: number, angle2: number) => {
    const x1 = cx + r * Math.cos(angle1);
    const y1 = cy - r * Math.sin(angle1);
    const x2 = cx + r * Math.cos(angle2);
    const y2 = cy - r * Math.sin(angle2);
    const largeArc = Math.abs(angle1 - angle2) > Math.PI ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 0 ${x2} ${y2}`;
  };

  const byStatus = summary?.by_status || {};
  const total = summary?.total || 0;
  const managed = (byStatus.MANAGED || 0) + (byStatus.FULLY_MANAGED || 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05, ease: [0.4, 0, 0.2, 1] }}
    >
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-2">
          <ShieldAlert className="h-4 w-4 text-accent" />
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted">
            Fleet Risk Score
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center md:flex-row md:items-start md:gap-8">
            {/* Gauge */}
            <div className="relative">
              <svg width="200" height="110" viewBox="0 0 200 110">
                <defs>
                  <linearGradient id="gauge-bg" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity="0.15" />
                    <stop offset="50%" stopColor="#f59e0b" stopOpacity="0.15" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0.15" />
                  </linearGradient>
                </defs>
                {/* Background arc */}
                <path
                  d={arcPath(startAngle, endAngle)}
                  fill="none"
                  stroke="url(#gauge-bg)"
                  strokeWidth={strokeW}
                  strokeLinecap="round"
                />
                {/* Filled arc */}
                <motion.path
                  d={arcPath(startAngle, filledAngle)}
                  fill="none"
                  stroke={color}
                  strokeWidth={strokeW}
                  strokeLinecap="round"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 1, delay: 0.3, ease: "easeOut" }}
                />
                {/* Score text */}
                <text x={cx} y={cy - 10} textAnchor="middle" className="fill-foreground text-3xl font-bold" style={{ fontSize: "32px", fontWeight: 700 }}>
                  {score}
                </text>
                <text x={cx} y={cy + 8} textAnchor="middle" style={{ fontSize: "11px", fontWeight: 500, fill: color }}>
                  {label}
                </text>
              </svg>
            </div>

            {/* Breakdown */}
            <div className="mt-2 flex-1 space-y-2 md:mt-1">
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-muted">Managed (MDM+EDR)</span>
                  <span className="font-semibold">{managed}/{total}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Coverage</span>
                  <span className="font-semibold">{total > 0 ? Math.round((managed / total) * 100) : 0}%</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Without EDR</span>
                  <span className="font-semibold text-red-400">{byStatus.NO_EDR || 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Without MDM</span>
                  <span className="font-semibold text-amber-400">{byStatus.NO_MDM || 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">IDP Only</span>
                  <span className="font-semibold text-orange-400">{byStatus.IDP_ONLY || 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted">Stale</span>
                  <span className="font-semibold text-muted">{byStatus.STALE || 0}</span>
                </div>
              </div>
              <p className="pt-1 text-[10px] text-muted leading-relaxed">
                Score 0–100 based on fleet posture. Each device is weighted by status:
                Fully Managed=100, Managed=80, Server=75, No MDM=40, No EDR=25, IDP Only=15, Stale=5.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
