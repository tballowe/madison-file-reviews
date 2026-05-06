import type { FolderListing, FolderNode, AnalysisReport } from "@/types";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error((body as { error?: string }).error || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function fetchFolderListing(path: string): Promise<FolderListing> {
  return fetchJson(`/api/folders?path=${encodeURIComponent(path)}`);
}

export async function fetchFolderTree(
  path: string,
  depth = 2,
): Promise<{ tree: FolderNode[] }> {
  return fetchJson(`/api/folders/tree?path=${encodeURIComponent(path)}&depth=${depth}`);
}

export async function startAnalysis(
  path: string,
  options: { recursive?: boolean; maxDepth?: number; tier?: "sonnet" | "opus" } = {},
): Promise<{ id: string; status: string }> {
  return fetchJson("/api/analysis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, ...options }),
  });
}

export async function fetchAnalysis(id: string): Promise<AnalysisReport> {
  return fetchJson(`/api/analysis/${id}`);
}

export async function fetchAnalysisHistory(): Promise<{ reports: AnalysisReport[] }> {
  return fetchJson("/api/analysis");
}

export async function downloadAnalysisPdf(id: string): Promise<void> {
  const res = await fetch(`/api/analysis/${id}/pdf`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error((body as { error?: string }).error || res.statusText);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const disposition = res.headers.get("Content-Disposition");
  const filename = disposition?.match(/filename="(.+)"/)?.[1] || `analysis_${id}.pdf`;
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
