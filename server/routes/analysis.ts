import { Router } from "express";
import { randomUUID } from "crypto";
import { createReport, completeReport, getReport, listReports } from "../db.js";
import { buildDirectorySummary, runAnalysis } from "../services/analyzer.js";
import { logger } from "../logger.js";

const router = Router();

router.post("/api/analysis", async (req, res) => {
  try {
    const { path, recursive = true, maxDepth = 5, tier = "sonnet" } = req.body as {
      path: string;
      recursive?: boolean;
      maxDepth?: number;
      tier?: "sonnet" | "opus";
    };

    if (!path) {
      res.status(400).json({ error: "path is required" });
      return;
    }

    const id = randomUUID();
    createReport(id, path);
    res.json({ id, status: "processing" });

    (async () => {
      try {
        const summary = await buildDirectorySummary(path, recursive ? maxDepth : 1);
        const result = await runAnalysis(summary, tier);

        completeReport(id, {
          status: "complete",
          summary: result.content.summary,
          overallScore: result.content.overallScore,
          findings: result.content.findings,
          recommendations: result.content.recommendations,
          model: result.model,
          inputTokens: result.inputTokens,
          outputTokens: result.outputTokens,
        });

        logger.info({ id, path, findings: result.content.findings.length }, "analysis complete");
      } catch (err) {
        logger.error({ id, err: (err as Error).message }, "analysis failed");
        completeReport(id, {
          status: "error",
          error: (err as Error).message,
        });
      }
    })();
  } catch (err) {
    logger.error({ err: (err as Error).message }, "analysis request failed");
    res.status(500).json({ error: (err as Error).message });
  }
});

router.get("/api/analysis/:id", async (req, res) => {
  const report = getReport(req.params.id);
  if (!report) {
    res.status(404).json({ error: "Report not found" });
    return;
  }
  res.json(report);
});

router.get("/api/analysis", async (_req, res) => {
  const reports = listReports();
  res.json({ reports });
});

export default router;
