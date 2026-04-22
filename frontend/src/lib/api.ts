import type { ApiDevicesResponse, ApiSyncLastResponse, Insight, StatusSnapshot, Summary, TrendsResponse } from "../types";

const API_BASE = "";

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, options);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getDevices: (status?: string | null, source?: string | null) => {
    const params = new URLSearchParams();
    if (status) params.append("status", status);
    if (source) params.append("source", source);
    const qs = params.toString();
    return fetchJson<ApiDevicesResponse>(`/api/devices${qs ? `?${qs}` : ""}`);
  },

  getSummary: () => fetchJson<Summary>("/api/summary"),

  getLastSync: () => fetchJson<ApiSyncLastResponse>("/api/sync/last"),

  triggerSync: () =>
    fetchJson<{ message: string; started: boolean }>("/api/sync/trigger", {
      method: "POST",
    }),

  getHistory: (limit = 30) =>
    fetchJson<{ history: StatusSnapshot[] }>(`/api/history?limit=${limit}`),

  getTrends: () => fetchJson<TrendsResponse>("/api/trends"),

  getInsights: () => fetchJson<{ actions: Insight[] }>("/api/insights"),

  getReport: () => fetchJson<{ report: string }>("/api/report"),
};
