import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import type { Device } from "../types";

const PAGE_SIZE = 10;

interface LowConfidenceProps {
  devices: Device[];
}

export function LowConfidence({ devices }: LowConfidenceProps) {
  const [page, setPage] = useState(1);

  const items = useMemo(
    () => devices.filter((d) => (d.confidence_score || 0) < 0.5),
    [devices]
  );

  const totalPages = Math.ceil(items.length / PAGE_SIZE);
  const start = (page - 1) * PAGE_SIZE;
  const pageItems = items.slice(start, start + PAGE_SIZE);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.5, ease: [0.4, 0, 0.2, 1] }}
    >
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-4">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted">
            Low Confidence Devices (&lt; 0.5)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted">
                  <th className="pb-3 font-medium">Owner</th>
                  <th className="pb-3 font-medium">Hostname</th>
                  <th className="pb-3 font-medium">Sources</th>
                  <th className="pb-3 font-medium text-right">Confidence</th>
                  <th className="pb-3 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((d) => (
                  <tr
                    key={d.canonical_id}
                    className="border-b border-border/50 transition-colors hover:bg-card/50 last:border-b-0"
                  >
                    <td className="py-3 pr-4 font-medium">
                      {d.owner_email || "N/A"}
                    </td>
                    <td className="py-3 pr-4 text-muted">
                      {(d.hostnames || []).join(", ") || "N/A"}
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex flex-wrap gap-1">
                        {(d.sources || []).map((s) => (
                          <span
                            key={s}
                            className="rounded border border-border bg-card px-1.5 py-0.5 text-[10px] text-muted"
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 text-right font-semibold text-red-400">
                      {d.confidence_score?.toFixed(2) ?? "0.00"}
                    </td>
                    <td className="py-3 text-xs text-muted">
                      {d.match_reason || ""}
                    </td>
                  </tr>
                ))}
                {pageItems.length === 0 && (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-8 text-center text-sm text-muted"
                    >
                      No low confidence devices
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-border pt-4">
            <span className="text-xs text-muted">
              Showing {items.length > 0 ? start + 1 : 0}–
              {Math.min(start + PAGE_SIZE, items.length)} of {items.length}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft className="h-4 w-4" />
                Prev
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || totalPages === 0}
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
