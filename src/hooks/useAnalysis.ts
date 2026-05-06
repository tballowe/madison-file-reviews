import { useMutation, useQuery } from "@tanstack/react-query";
import { startAnalysis, fetchAnalysis, fetchAnalysisHistory } from "@/lib/api";

export function useStartAnalysis() {
  return useMutation({
    mutationFn: ({
      path,
      recursive,
      maxDepth,
      tier,
    }: {
      path: string;
      recursive?: boolean;
      maxDepth?: number;
      tier?: "sonnet" | "opus";
    }) => startAnalysis(path, { recursive, maxDepth, tier }),
  });
}

export function useAnalysisReport(id: string | null) {
  return useQuery({
    queryKey: ["analysis", id],
    queryFn: () => fetchAnalysis(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.status !== "processing") return false;
      return 2000;
    },
  });
}

export function useAnalysisHistory() {
  return useQuery({
    queryKey: ["analysis-history"],
    queryFn: () => fetchAnalysisHistory(),
  });
}
