import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "N/A";
  return new Date(iso).toLocaleString();
}

export function normalizeOs(os: string | null | undefined): string {
  if (!os) return "Unknown";
  const lower = os.toLowerCase().trim();
  if (["mac", "mac os x", "macos", "darwin", "osx"].some((w) => lower.includes(w))) return "macOS";
  if (["windows", "win"].some((w) => lower.includes(w))) return "Windows";
  if (["linux", "ubuntu", "centos", "rhel", "debian"].some((w) => lower.includes(w))) return "Linux";
  return os;
}

const SOURCE_ABBREV: Record<string, string> = {
  crowdstrike: "CS",
  jumpcloud: "JC",
  okta: "OKT",
};

export function shortSource(source: string): string {
  return SOURCE_ABBREV[source] || source;
}
