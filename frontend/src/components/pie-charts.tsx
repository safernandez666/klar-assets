import { motion } from "motion/react";
import { PieChart as PieIcon } from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import type { Summary } from "../types";

const STATUS_COLORS: Record<string, string> = {
  FULLY_MANAGED: "#34d399",
  MANAGED: "#60a5fa",
  NO_EDR: "#f87171",
  NO_MDM: "#fbbf24",
  IDP_ONLY: "#fb923c",
  STALE: "#9ca3af",
  UNKNOWN: "#6b7280",
};

const STATUS_LABELS: Record<string, string> = {
  FULLY_MANAGED: "Fully Managed",
  MANAGED: "Managed",
  NO_EDR: "No EDR",
  NO_MDM: "No MDM",
  IDP_ONLY: "IDP Only",
  STALE: "Stale",
  UNKNOWN: "Unknown",
};

const SOURCE_COLORS: Record<string, string> = {
  crowdstrike: "#f87171",
  jumpcloud: "#60a5fa",
  okta: "#fbbf24",
};

interface PieChartsProps {
  summary: Summary | null;
}

export function PieCharts({ summary }: PieChartsProps) {
  const byStatus = summary?.by_status || {};
  const bySource = summary?.by_source || {};

  const statusData = Object.entries(byStatus)
    .filter(([, v]) => v > 0)
    .map(([key, value]) => ({
      name: STATUS_LABELS[key] || key,
      value,
      color: STATUS_COLORS[key] || "#6b7280",
    }));

  const sourceData = Object.entries(bySource)
    .filter(([, v]) => v > 0)
    .map(([key, value]) => ({
      name: key,
      value,
      color: SOURCE_COLORS[key] || "#6b7280",
    }));

  if (statusData.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.25, ease: [0.4, 0, 0.2, 1] }}
    >
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-4">
          <PieIcon className="h-4 w-4 text-accent" />
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted">
            Distribution
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
            {/* Status distribution */}
            <div>
              <h4 className="mb-2 text-center text-xs font-semibold text-muted">By Status</h4>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={statusData}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={90}
                      paddingAngle={2}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      {statusData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "rgba(17, 24, 39, 0.95)",
                        border: "1px solid rgba(255,255,255,0.1)",
                        borderRadius: "0.75rem",
                        fontSize: "12px",
                        color: "#f3f4f6",
                      }}
                      formatter={(value, name) => [String(value), String(name)]}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: "11px" }}
                      formatter={(value: string) => <span className="text-muted">{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Source distribution */}
            <div>
              <h4 className="mb-2 text-center text-xs font-semibold text-muted">By Source (raw)</h4>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={sourceData}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={90}
                      paddingAngle={2}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      {sourceData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "rgba(17, 24, 39, 0.95)",
                        border: "1px solid rgba(255,255,255,0.1)",
                        borderRadius: "0.75rem",
                        fontSize: "12px",
                        color: "#f3f4f6",
                      }}
                      formatter={(value, name) => [String(value), String(name)]}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: "11px" }}
                      formatter={(value: string) => <span className="text-muted">{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
