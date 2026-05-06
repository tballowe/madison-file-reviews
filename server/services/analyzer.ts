import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { config } from "../config.js";
import { logger } from "../logger.js";
import { listFolderRecursive } from "./filescom.js";
import type { FileItem, DirectorySummary, FolderSummary } from "./types.js";

let client: Anthropic | null = null;

function getClient(): Anthropic {
  if (!client) {
    client = new Anthropic({ apiKey: config.anthropicApiKey });
  }
  return client;
}

const AnalysisResultSchema = z.object({
  summary: z.string(),
  overallScore: z.enum(["good", "needs-attention", "critical"]),
  findings: z.array(
    z.object({
      severity: z.enum(["critical", "warning", "info"]),
      category: z.enum([
        "missing-date-range",
        "low-file-count",
        "missing-file-type",
        "missing-board",
        "naming-anomaly",
        "scraper-failure",
        "other",
      ]),
      title: z.string(),
      description: z.string(),
      affectedPath: z.string(),
      expectedBehavior: z.optional(z.string()),
      actualBehavior: z.string(),
    }),
  ),
  recommendations: z.array(z.string()),
});

type AnalysisResult = z.infer<typeof AnalysisResultSchema>;

const SYSTEM_PROMPT = `You are a data quality analyst for a government document management system.
You analyze scraped file directories containing agendas, minutes, agenda packets, and other documents for cities and counties. Your job is to detect gaps, inconsistencies, and completeness issues in the scraped data.

Common issues to look for:
- Missing months or date ranges (e.g., no files for June-August of a year when other months have files)
- Significantly fewer files in one year vs. others (e.g., 12 files one year vs 48+ in adjacent years)
- Missing file types (e.g., agendas present but no minutes for the same time periods)
- Missing boards/commissions compared to other time periods
- Files with anomalous naming patterns suggesting scraper errors
- Sudden drops or spikes in file counts suggesting scraper failures or configuration issues
- Gaps in otherwise regular patterns (e.g., monthly meetings that skip several months)

When analyzing, consider:
- Government boards typically meet on regular schedules (weekly, biweekly, monthly)
- Most boards produce both agendas and minutes for each meeting
- A sudden drop in file count likely means the scraper missed data, not that meetings stopped
- File naming patterns within a folder should be consistent

Be specific about what's missing and where. Reference exact folder paths and date ranges.`;

function zodToJsonSchema(schema: z.ZodType<unknown>): Record<string, unknown> {
  type ZodWithToJson = { toJSONSchema?: (s: unknown) => Record<string, unknown> };
  const maybe = (z as unknown as ZodWithToJson).toJSONSchema;
  if (typeof maybe === "function") {
    const raw = maybe(schema);
    return sanitizeForAnthropic(raw);
  }
  return { type: "object", additionalProperties: true };
}

function sanitizeForAnthropic(s: Record<string, unknown>): Record<string, unknown> {
  const clone = JSON.parse(JSON.stringify(s)) as Record<string, unknown>;
  const strip = (obj: unknown) => {
    if (obj && typeof obj === "object") {
      const rec = obj as Record<string, unknown>;
      delete rec.$schema;
      delete rec.$id;
      for (const v of Object.values(rec)) strip(v);
    }
  };
  strip(clone);
  if (!clone.type) clone.type = "object";
  return clone;
}

export async function buildDirectorySummary(
  path: string,
  maxDepth: number,
): Promise<DirectorySummary> {
  logger.info({ path, maxDepth }, "collecting directory listing");
  const allItems = await listFolderRecursive(path, maxDepth);
  const files = allItems.filter((i) => i.type === "file");

  const folderMap = new Map<string, FileItem[]>();
  for (const file of files) {
    const folderPath = file.path.substring(0, file.path.lastIndexOf("/")) || path;
    const existing = folderMap.get(folderPath) || [];
    existing.push(file);
    folderMap.set(folderPath, existing);
  }

  const folders: FolderSummary[] = [];
  for (const [folderPath, folderFiles] of folderMap) {
    const fileTypes: Record<string, number> = {};
    let earliest: string | null = null;
    let latest: string | null = null;

    for (const f of folderFiles) {
      const ext = f.display_name.includes(".")
        ? f.display_name.substring(f.display_name.lastIndexOf(".")).toLowerCase()
        : "no-extension";
      fileTypes[ext] = (fileTypes[ext] || 0) + 1;

      const date = f.mtime || f.provided_mtime;
      if (date) {
        if (!earliest || date < earliest) earliest = date;
        if (!latest || date > latest) latest = date;
      }
    }

    folders.push({
      path: folderPath,
      name: folderPath.split("/").pop() || folderPath,
      fileCount: folderFiles.length,
      fileTypes,
      dateRange: { earliest, latest },
      files: folderFiles.map((f) => ({
        name: f.display_name,
        size: f.size,
        mtime: f.mtime || f.provided_mtime,
      })),
    });
  }

  return {
    path,
    name: path.split("/").pop() || path,
    totalFiles: files.length,
    folders,
  };
}

export interface RunAnalysisResult {
  content: AnalysisResult;
  model: string;
  inputTokens: number;
  outputTokens: number;
}

export async function runAnalysis(
  summary: DirectorySummary,
  tier: "sonnet" | "opus" = "sonnet",
): Promise<RunAnalysisResult> {
  const modelId = tier === "opus" ? "claude-opus-4-6" : "claude-sonnet-4-6";
  const inputSchema = zodToJsonSchema(AnalysisResultSchema);

  const userMessage = `Analyze this scraped file directory for completeness and data quality issues.

Directory: ${summary.path}
Total files: ${summary.totalFiles}
Total subfolders with files: ${summary.folders.length}

${JSON.stringify(summary.folders, null, 2)}`;

  logger.info(
    { path: summary.path, tier, folders: summary.folders.length, files: summary.totalFiles },
    "running Claude analysis",
  );

  const response = await getClient().messages.create({
    model: modelId,
    max_tokens: 4096,
    system: SYSTEM_PROMPT,
    tools: [
      {
        name: "report_findings",
        description:
          "Emit the structured analysis report. You MUST call this tool exactly once with a well-formed object matching the input schema.",
        input_schema: inputSchema as Anthropic.Tool["input_schema"],
      },
    ],
    tool_choice: { type: "tool", name: "report_findings" },
    messages: [{ role: "user", content: userMessage }],
  });

  const toolUse = response.content.find(
    (b): b is Extract<(typeof response.content)[number], { type: "tool_use" }> =>
      b.type === "tool_use",
  );

  if (!toolUse) {
    throw new Error(`Claude did not return a tool_use block (stop_reason=${response.stop_reason})`);
  }

  const parsed = AnalysisResultSchema.safeParse(toolUse.input);
  if (!parsed.success) {
    throw new Error(`Claude output failed validation: ${parsed.error.message.slice(0, 300)}`);
  }

  return {
    content: parsed.data,
    model: modelId,
    inputTokens: response.usage.input_tokens,
    outputTokens: response.usage.output_tokens,
  };
}
