import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "N/A";
  return new Date(iso).toLocaleString();
}

const SOURCE_ABBREV: Record<string, string> = {
  crowdstrike: "CS",
  jumpcloud: "JC",
  okta: "OKT",
};

export function shortSource(source: string): string {
  return SOURCE_ABBREV[source] || source;
}
