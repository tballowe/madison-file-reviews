import { useState } from "react";
import { useFolderListing } from "@/hooks/useFolders";
import { useStartAnalysis, useAnalysisReport } from "@/hooks/useAnalysis";
import Breadcrumbs from "./Breadcrumbs";
import FolderTree from "./FolderTree";
import FileList from "./FileList";
import AnalysisButton from "./AnalysisButton";
import AnalysisReport from "./AnalysisReport";

export default function FolderBrowser() {
  const [currentPath, setCurrentPath] = useState("/");
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);

  const { data, isLoading, error } = useFolderListing(currentPath);
  const startAnalysis = useStartAnalysis();
  const { data: report } = useAnalysisReport(analysisId);

  const handleNavigate = (path: string) => {
    setCurrentPath(path);
    setShowReport(false);
    setAnalysisId(null);
  };

  const handleStartAnalysis = (options: {
    path: string;
    recursive: boolean;
    tier: "sonnet" | "opus";
  }) => {
    startAnalysis.mutate(options, {
      onSuccess: (data) => {
        setAnalysisId(data.id);
        setShowReport(true);
      },
    });
  };

  if (showReport && report) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)]">
        <aside className="w-72 border-r bg-muted/30 shrink-0 hidden lg:block">
          <FolderTree currentPath={currentPath} onNavigate={handleNavigate} />
        </aside>
        <div className="flex-1 overflow-auto p-6">
          <AnalysisReport
            report={report}
            onBack={() => {
              setShowReport(false);
              setAnalysisId(null);
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <aside className="w-72 border-r bg-muted/30 shrink-0 hidden lg:block">
        <FolderTree currentPath={currentPath} onNavigate={handleNavigate} />
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b px-6 py-3">
          {data?.breadcrumbs && (
            <Breadcrumbs segments={data.breadcrumbs} onNavigate={handleNavigate} />
          )}
        </div>

        <div className="px-6 py-3">
          <AnalysisButton
            path={currentPath}
            onStart={handleStartAnalysis}
            isLoading={startAnalysis.isPending}
          />
        </div>

        <div className="flex-1 overflow-auto px-6">
          {isLoading && (
            <div className="py-12 text-center text-muted-foreground">
              Loading files...
            </div>
          )}
          {error && (
            <div className="py-12 text-center text-destructive">
              Error: {(error as Error).message}
            </div>
          )}
          {data && <FileList items={data.items} onNavigate={handleNavigate} />}
        </div>
      </div>
    </div>
  );
}
