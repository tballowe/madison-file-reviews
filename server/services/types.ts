export interface FileItem {
  path: string;
  display_name: string;
  type: "directory" | "file";
  size: number | null;
  mtime: string | null;
  provided_mtime: string | null;
  mime_type: string | null;
}

export interface FolderListing {
  items: FileItem[];
  path: string;
  breadcrumbs: PathSegment[];
}

export interface PathSegment {
  name: string;
  path: string;
}

export interface FolderNode {
  name: string;
  path: string;
  children?: FolderNode[];
  fileCount?: number;
}

export interface DirectorySummary {
  path: string;
  name: string;
  totalFiles: number;
  folders: FolderSummary[];
}

export interface FolderSummary {
  path: string;
  name: string;
  fileCount: number;
  fileTypes: Record<string, number>;
  dateRange: { earliest: string | null; latest: string | null };
  files: FileSummary[];
}

export interface FileSummary {
  name: string;
  size: number | null;
  mtime: string | null;
}

export interface AnalysisFinding {
  severity: "critical" | "warning" | "info";
  category: string;
  title: string;
  description: string;
  affectedPath: string;
  expectedBehavior?: string;
  actualBehavior: string;
}

export interface AnalysisReport {
  id: string;
  path: string;
  status: "processing" | "complete" | "error";
  createdAt: string;
  completedAt?: string;
  summary?: string;
  overallScore?: "good" | "needs-attention" | "critical";
  findings?: AnalysisFinding[];
  recommendations?: string[];
  error?: string;
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
}
