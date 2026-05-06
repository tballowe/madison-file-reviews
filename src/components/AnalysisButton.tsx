import { useState } from "react";
import { ScanSearch, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface AnalysisButtonProps {
  path: string;
  onStart: (options: { path: string; recursive: boolean; tier: "sonnet" | "opus" }) => void;
  isLoading: boolean;
}

export default function AnalysisButton({ path, onStart, isLoading }: AnalysisButtonProps) {
  const [recursive, setRecursive] = useState(true);

  if (!path || path === "/") {
    return null;
  }

  return (
    <div className="flex items-center gap-4 p-4 border rounded-lg bg-card">
      <div className="flex-1">
        <div className="font-medium text-sm">Analyze Directory</div>
        <div className="text-xs text-muted-foreground mt-0.5 truncate max-w-md">
          {path}
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={recursive}
          onChange={(e) => setRecursive(e.target.checked)}
          className="rounded"
        />
        Include subfolders
      </label>
      <Button
        size="lg"
        onClick={() => onStart({ path, recursive, tier: "sonnet" })}
        disabled={isLoading}
      >
        {isLoading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <ScanSearch className="size-4" />
        )}
        {isLoading ? "Analyzing..." : "Run Analysis"}
      </Button>
    </div>
  );
}
