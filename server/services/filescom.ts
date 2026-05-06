import { config } from "../config.js";
import { logger } from "../logger.js";
import type { FileItem, FolderNode, PathSegment } from "./types.js";

const ITEMS_PER_PAGE = 1000;
const MAX_RETRIES = 3;

function encodePathForUrl(path: string): string {
  return path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

async function fetchWithRetry(url: string, retries = MAX_RETRIES): Promise<Response> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    const res = await fetch(url, {
      headers: { "X-FilesAPI-Key": config.filesApiKey },
    });

    if (res.status === 429 && attempt < retries) {
      const delay = Math.pow(2, attempt) * 1000;
      logger.warn({ attempt, delay }, "Files.com rate limited, retrying");
      await new Promise((r) => setTimeout(r, delay));
      continue;
    }

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`Files.com API error ${res.status}: ${body}`);
    }

    return res;
  }
  throw new Error("Files.com API max retries exceeded");
}

export async function listFolder(path: string): Promise<FileItem[]> {
  const items: FileItem[] = [];
  let cursor: string | null = null;

  do {
    const encodedPath = encodePathForUrl(path);
    let url = `${config.filesBaseUrl}/folders/${encodedPath}?per_page=${ITEMS_PER_PAGE}`;
    if (cursor) url += `&cursor=${encodeURIComponent(cursor)}`;

    const res = await fetchWithRetry(url);
    const headerCursor = res.headers.get("x-files-cursor");
    cursor = headerCursor || null;

    const data = (await res.json()) as FileItem[];
    items.push(...data);
  } while (cursor);

  return items;
}

export async function listFolderRecursive(
  path: string,
  maxDepth = 5,
  currentDepth = 0,
): Promise<FileItem[]> {
  if (currentDepth >= maxDepth) return [];

  const items = await listFolder(path);
  const allItems: FileItem[] = [...items];

  const subfolders = items.filter((i) => i.type === "directory");
  for (const folder of subfolders) {
    const children = await listFolderRecursive(folder.path, maxDepth, currentDepth + 1);
    allItems.push(...children);
  }

  return allItems;
}

export async function getFolderTree(path: string, depth = 2): Promise<FolderNode[]> {
  const items = await listFolder(path);

  const folders = items.filter((i) => i.type === "directory");
  const files = items.filter((i) => i.type === "file");

  const nodes: FolderNode[] = [];

  for (const folder of folders) {
    const node: FolderNode = {
      name: folder.display_name,
      path: folder.path,
    };

    if (depth > 1) {
      try {
        node.children = await getFolderTree(folder.path, depth - 1);
      } catch {
        node.children = [];
      }
    }

    nodes.push(node);
  }

  return nodes;
}

export function buildBreadcrumbs(path: string): PathSegment[] {
  const segments: PathSegment[] = [{ name: "Root", path: "/" }];
  if (!path || path === "/") return segments;

  const parts = path.replace(/^\/|\/$/g, "").split("/");
  let current = "";
  for (const part of parts) {
    current += "/" + part;
    segments.push({ name: part, path: current });
  }

  return segments;
}
