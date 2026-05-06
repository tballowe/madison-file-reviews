import { useState } from "react";
import { Loader2, CheckCircle2, XCircle, ArrowLeft, Download } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import FindingSeverityBadge from "./FindingSeverityBadge";
import { downloadAnalysisPdf } from "@/lib/api";
import type { AnalysisReport as Report } from "@/types";

interface AnalysisReportProps {
  report: Report;
  onBack: () => void;
}

function ScoreBadge({ score }: { score: string }) {
  switch (score) {
    case "good":
      return <Badge variant="success"><CheckCircle2 className="size-3" /> Good</Badge>;
    case "needs-attention":
      return <Badge variant="warning">Needs Attention</Badge>;
    case "critical":
      return <Badge variant="critical"><XCircle className="size-3" /> Critical Issues</Badge>;
    default:
      return null;
  }
}

export default function AnalysisReport({ report, onBack }: AnalysisReportProps) {
  const [exporting, setExporting] = useState(false);
  if (report.status === "processing") {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <Loader2 className="size-10 animate-spin text-primary" />
        <div className="text-center">
          <p className="font-medium">Analyzing directory...</p>
          <p className="text-sm text-muted-foreground mt-1">{report.path}</p>
          <p className="text-xs text-muted-foreground mt-2">
            This may take a minute for large directories
          </p>
        </div>
      </div>
    );
  }

  if (report.status === "error") {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" /> Back to browser
        </Button>
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">Analysis Failed</CardTitle>
            <CardDescription>{report.path}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{report.error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const critical = report.findings?.filter((f) => f.severity === "critical") || [];
  const warnings = report.findings?.filter((f) => f.severity === "warning") || [];
  const infos = report.findings?.filter((f) => f.severity === "info") || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" /> Back to browser
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={exporting}
          onClick={async () => {
            setExporting(true);
            try {
              await downloadAnalysisPdf(report.id);
            } catch (e) {
              console.error("PDF export failed:", e);
            } finally {
              setExporting(false);
            }
          }}
        >
          {exporting ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
          Export PDF
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>Analysis Report</CardTitle>
              <CardDescription className="mt-1">{report.path}</CardDescription>
            </div>
            {report.overallScore && <ScoreBadge score={report.overallScore} />}
          </div>
        </CardHeader>
        <CardContent>
          {report.summary && (
            <p className="text-sm leading-relaxed">{report.summary}</p>
          )}
          <div className="flex gap-4 mt-3 text-xs text-muted-foreground">
            <span>{report.findings?.length || 0} findings</span>
            {report.model && <span>Model: {report.model}</span>}
            {report.completedAt && (
              <span>
                Completed: {new Date(report.completedAt).toLocaleString()}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {critical.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-red-700 dark:text-red-400">
            Critical Issues ({critical.length})
          </h3>
          {critical.map((f, i) => (
            <FindingCard key={i} finding={f} />
          ))}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-amber-700 dark:text-amber-400">
            Warnings ({warnings.length})
          </h3>
          {warnings.map((f, i) => (
            <FindingCard key={i} finding={f} />
          ))}
        </div>
      )}

      {infos.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-blue-700 dark:text-blue-400">
            Info ({infos.length})
          </h3>
          {infos.map((f, i) => (
            <FindingCard key={i} finding={f} />
          ))}
        </div>
      )}

      {report.recommendations && report.recommendations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recommendations</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc list-inside space-y-1 text-sm">
              {report.recommendations.map((rec, i) => (
                <li key={i}>{rec}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function FindingCard({ finding }: { finding: Report["findings"] extends (infer T)[] | undefined ? T : never }) {
  if (!finding) return null;
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start gap-3">
          <FindingSeverityBadge severity={finding.severity} />
          <div className="flex-1 min-w-0">
            <h4 className="font-medium text-sm">{finding.title}</h4>
            <p className="text-sm text-muted-foreground mt-1">{finding.description}</p>
            <div className="mt-2 space-y-1 text-xs">
              <div>
                <span className="font-medium">Path:</span>{" "}
                <span className="text-muted-foreground">{finding.affectedPath}</span>
              </div>
              <div>
                <span className="font-medium">Actual:</span>{" "}
                <span className="text-muted-foreground">{finding.actualBehavior}</span>
              </div>
              {finding.expectedBehavior && (
                <div>
                  <span className="font-medium">Expected:</span>{" "}
                  <span className="text-muted-foreground">{finding.expectedBehavior}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
