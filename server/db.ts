import Database from "better-sqlite3";
import { mkdirSync, existsSync } from "fs";
import { join } from "path";
import type { AnalysisReport } from "./services/types.js";

const DATA_DIR = join(process.cwd(), "data");
if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(join(DATA_DIR, "reviews.db"));
db.pragma("journal_mode = WAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    summary TEXT,
    overall_score TEXT,
    findings TEXT,
    recommendations TEXT,
    error TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER
  )
`);

const insertStmt = db.prepare(`
  INSERT INTO analysis_reports (id, path, status, created_at)
  VALUES (?, ?, 'processing', ?)
`);

const updateStmt = db.prepare(`
  UPDATE analysis_reports
  SET status = ?, completed_at = ?, summary = ?, overall_score = ?,
      findings = ?, recommendations = ?, error = ?, model = ?,
      input_tokens = ?, output_tokens = ?
  WHERE id = ?
`);

const getStmt = db.prepare(`SELECT * FROM analysis_reports WHERE id = ?`);
const listStmt = db.prepare(`SELECT * FROM analysis_reports ORDER BY created_at DESC LIMIT 50`);

export function createReport(id: string, path: string): void {
  insertStmt.run(id, path, new Date().toISOString());
}

export function completeReport(id: string, report: Partial<AnalysisReport>): void {
  updateStmt.run(
    report.status || "complete",
    new Date().toISOString(),
    report.summary || null,
    report.overallScore || null,
    report.findings ? JSON.stringify(report.findings) : null,
    report.recommendations ? JSON.stringify(report.recommendations) : null,
    report.error || null,
    report.model || null,
    report.inputTokens || null,
    report.outputTokens || null,
    id,
  );
}

export function getReport(id: string): AnalysisReport | null {
  const row = getStmt.get(id) as Record<string, unknown> | undefined;
  if (!row) return null;
  return deserializeReport(row);
}

export function listReports(): AnalysisReport[] {
  const rows = listStmt.all() as Record<string, unknown>[];
  return rows.map(deserializeReport);
}

function deserializeReport(row: Record<string, unknown>): AnalysisReport {
  return {
    id: row.id as string,
    path: row.path as string,
    status: row.status as AnalysisReport["status"],
    createdAt: row.created_at as string,
    completedAt: (row.completed_at as string) || undefined,
    summary: (row.summary as string) || undefined,
    overallScore: (row.overall_score as AnalysisReport["overallScore"]) || undefined,
    findings: row.findings ? JSON.parse(row.findings as string) : undefined,
    recommendations: row.recommendations ? JSON.parse(row.recommendations as string) : undefined,
    error: (row.error as string) || undefined,
    model: (row.model as string) || undefined,
    inputTokens: (row.input_tokens as number) || undefined,
    outputTokens: (row.output_tokens as number) || undefined,
  };
}
