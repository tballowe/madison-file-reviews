import express from "express";
import { existsSync } from "fs";
import { join } from "path";
import { config, validateConfig } from "./config.js";
import { logger, requestLogger } from "./logger.js";
import foldersRouter from "./routes/folders.js";
import analysisRouter from "./routes/analysis.js";
import "./db.js";

validateConfig();

const app = express();

app.use(express.json({ limit: "1mb" }));
app.use(requestLogger);

app.use(foldersRouter);
app.use(analysisRouter);

app.get("/api/ping", (_req, res) => {
  res.json({ ok: true, time: new Date().toISOString() });
});

const distPath = join(import.meta.dirname || ".", "../dist");
if (existsSync(join(distPath, "index.html"))) {
  app.use(express.static(distPath));
  app.use((_req, res) => {
    res.sendFile(join(distPath, "index.html"));
  });
}

app.listen(config.port, "0.0.0.0", () => {
  logger.info({ port: config.port }, "Madison File Reviews API listening");
});
