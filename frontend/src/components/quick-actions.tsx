import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Zap,
  AlertOctagon,
  AlertTriangle,
  Info,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface Action {
  priority: string;
  title: string;
  description: string;
}

interface QuickActionsProps {
  actions: Action[];
}

const PRIORITY_CONFIG: Record<string, {
  icon: typeof AlertOctagon;
  color: string;
  bg: string;
  border: string;
  label: string;
  sortOrder: number;
}> = {
  critical: {
    icon: AlertOctagon,
    color: "text-red-400",
    bg: "bg-red-500/5",
    border: "border-red-500/20",
    label: "CRITICAL",
    sortOrder: 0,
  },
  high: {
    icon: AlertTriangle,
    color: "text-amber-400",
    bg: "bg-amber-500/5",
    border: "border-amber-500/20",
    label: "HIGH",
    sortOrder: 1,
  },
  medium: {
    icon: Info,
    color: "text-blue-400",
    bg: "bg-blue-500/5",
    border: "border-blue-500/20",
    label: "MEDIUM",
    sortOrder: 2,
  },
  low: {
    icon: Info,
    color: "text-muted",
    bg: "bg-neutral-500/5",
    border: "border-neutral-500/20",
    label: "LOW",
    sortOrder: 3,
  },
  success: {
    icon: CheckCircle2,
    color: "text-emerald-400",
    bg: "bg-emerald-500/5",
    border: "border-emerald-500/20",
    label: "OK",
    sortOrder: 5,
  },
  info: {
    icon: Info,
    color: "text-blue-400",
    bg: "bg-blue-500/5",
    border: "border-blue-500/20",
    label: "INFO",
    sortOrder: 4,
  },
};

function ActionItem({ action, index }: { action: Action; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = PRIORITY_CONFIG[action.priority] || PRIORITY_CONFIG.info;
  const Icon = cfg.icon;

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2, delay: 0.1 + index * 0.04 }}
      role="listitem"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className={`w-full rounded-xl border ${cfg.border} ${cfg.bg} p-4 text-left transition-colors hover:bg-card/50 focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none`}
      >
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 shrink-0 ${cfg.color}`} aria-hidden="true">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${cfg.color} ${cfg.bg} border ${cfg.border}`}>
                {cfg.label}
              </span>
              <h4 className="text-sm font-semibold text-pretty">{action.title}</h4>
            </div>
            <AnimatePresence>
              {expanded && (
                <motion.p
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.15 }}
                  className="mt-2 text-xs leading-relaxed text-muted"
                >
                  {action.description}
                </motion.p>
              )}
            </AnimatePresence>
          </div>
          <div className="mt-0.5 shrink-0 text-muted opacity-50" aria-hidden="true">
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </div>
        </div>
      </button>
    </motion.div>
  );
}

export function QuickActions({ actions }: QuickActionsProps) {
  if (actions.length === 0) return null;

  const sorted = [...actions].sort((a, b) => {
    const aOrder = PRIORITY_CONFIG[a.priority]?.sortOrder ?? 99;
    const bOrder = PRIORITY_CONFIG[b.priority]?.sortOrder ?? 99;
    return aOrder - bOrder;
  });

  const urgent = sorted.filter((a) => a.priority === "critical" || a.priority === "high");
  const other = sorted.filter((a) => a.priority !== "critical" && a.priority !== "high");

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1, ease: [0.4, 0, 0.2, 1] }}
    >
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-4">
          <Zap className="h-4 w-4 text-amber-400" aria-hidden="true" />
          <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted">
            Quick Actions
          </CardTitle>
          {urgent.length > 0 && (
            <span className="ml-auto rounded-full bg-red-500/10 border border-red-500/20 px-2.5 py-0.5 text-[10px] font-semibold text-red-400">
              {urgent.length} urgent
            </span>
          )}
        </CardHeader>
        <CardContent>
          {urgent.length > 0 && (
            <div className="mb-4" role="list" aria-label="Urgent actions">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-red-400/70">
                Requires attention
              </h4>
              <div className="space-y-2">
                {urgent.map((action, i) => (
                  <ActionItem key={`urgent-${i}`} action={action} index={i} />
                ))}
              </div>
            </div>
          )}

          {other.length > 0 && (
            <div role="list" aria-label="Other recommendations">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted/70">
                Recommendations
              </h4>
              <div className="space-y-2">
                {other.map((action, i) => (
                  <ActionItem key={`other-${i}`} action={action} index={urgent.length + i} />
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
