import { Router } from "express";
import { listFolder, getFolderTree, buildBreadcrumbs } from "../services/filescom.js";
import { logger } from "../logger.js";

const router = Router();

router.get("/api/folders", async (req, res) => {
  try {
    const path = (req.query.path as string) || "/";
    const items = await listFolder(path);
    const breadcrumbs = buildBreadcrumbs(path);
    res.json({ items, path, breadcrumbs });
  } catch (err) {
    logger.error({ err: (err as Error).message }, "folder listing failed");
    res.status(500).json({ error: (err as Error).message });
  }
});

router.get("/api/folders/tree", async (req, res) => {
  try {
    const path = (req.query.path as string) || "/";
    const depth = parseInt((req.query.depth as string) || "2", 10);
    const tree = await getFolderTree(path, Math.min(depth, 3));
    res.json({ tree });
  } catch (err) {
    logger.error({ err: (err as Error).message }, "folder tree failed");
    res.status(500).json({ error: (err as Error).message });
  }
});

export default router;
