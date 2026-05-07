import os
import json
import uuid
import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import httpx
import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

load_dotenv()

FILES_API_KEY = os.getenv("FILES_API_KEY", "")
FILES_BASE_URL = os.getenv("FILES_BASE_URL", "https://app.files.com/api/rest/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("CLAUDE_API_KEY", "")

app = FastAPI(title="Madison File Reviews")


@app.exception_handler(422)
async def validation_exception_handler(request: Request, exc: Exception):
    import traceback
    print(f"422 ERROR on {request.method} {request.url}")
    traceback.print_exc()
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "reviews.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
    """)
    conn.commit()
    return conn


get_db()

# ---------------------------------------------------------------------------
# Files.com client
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
ITEMS_PER_PAGE = 1000


def _encode_path(path: str) -> str:
    from urllib.parse import quote
    return "/".join(quote(seg, safe="") for seg in path.split("/"))


async def _fetch_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        resp = await client.get(url, headers={"X-FilesAPI-Key": FILES_API_KEY})
        if resp.status_code == 429 and attempt < MAX_RETRIES:
            delay = 2 ** attempt
            await asyncio.sleep(delay)
            continue
        if resp.status_code >= 400:
            body = resp.text
            print(f"Files.com API error: {resp.status_code} for URL: {url}")
            print(f"  Response: {body[:500]}")
            raise HTTPException(status_code=502, detail=f"Files.com returned {resp.status_code}: {body[:200]}")
        return resp
    raise HTTPException(status_code=502, detail="Files.com rate limit exceeded")


async def list_folder(path: str) -> list[dict]:
    if path and not path.startswith("/"):
        path = "/" + path
    items: list[dict] = []
    cursor: Optional[str] = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            encoded = _encode_path(path)
            url = f"{FILES_BASE_URL}/folders/{encoded}?per_page={ITEMS_PER_PAGE}"
            print(f"Files.com request: {url}")
            if cursor:
                url += f"&cursor={cursor}"
            resp = await _fetch_with_retry(client, url)
            cursor = resp.headers.get("x-files-cursor")
            items.extend(resp.json())
            if not cursor:
                break
    return items


async def list_folder_recursive(path: str, max_depth: int = 5, current_depth: int = 0) -> list[dict]:
    if current_depth >= max_depth:
        return []
    items = await list_folder(path)
    all_items = list(items)
    for item in items:
        if item.get("type") == "directory":
            children = await list_folder_recursive(item["path"], max_depth, current_depth + 1)
            all_items.extend(children)
    return all_items


def build_breadcrumbs(path: str) -> list[dict]:
    segments = [{"name": "Root", "path": "/"}]
    if not path or path == "/":
        return segments
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        segments.append({"name": part, "path": current})
    return segments


# ---------------------------------------------------------------------------
# Claude analyzer
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a data completeness analyst. You review directories of scraped files and identify gaps, inconsistencies, and quality issues.

You will receive a directory listing organized by subfolder with file counts and filenames. Your job is to study the data, identify patterns, and report anything that looks incomplete, inconsistent, or broken.

APPROACH:
- Look at the data with fresh eyes. Understand what it contains before judging it.
- Compare sibling folders to each other — if most have 50+ files but two have 3, that's notable.
- Look for patterns in filenames and notice when those patterns break.
- Look for numerical patterns — if file counts are suspiciously uniform (e.g., every folder has exactly 30 files), that likely indicates a scraper pagination limit.
- Notice gaps in sequences (dates, numbers, categories).
- Flag filesystem artifacts (@eaDir, Thumbs.db, .DS_Store, SynoEAStream, etc.) that aren't real content.
- Consider whether the directory structure itself makes sense or has orphaned/misplaced content.

REPORT FORMAT:
- Write a brief summary (2-3 sentences) of the directory's overall health.
- Create a SEPARATE finding for each distinct issue you identify. Be specific — include folder paths, file counts, and concrete examples.
- Group related issues when they share a root cause (e.g., a pagination limit hitting many folders = one finding listing all affected folders).
- Provide actionable recommendations for fixing what you found."""

ANALYSIS_TOOL = {
    "name": "report_findings",
    "description": "Emit the structured analysis report. You MUST call this tool exactly once. The findings array MUST NOT be empty if any issues exist.",
    "input_schema": {
        "type": "object",
        "required": ["summary", "overallScore", "findings", "recommendations"],
        "properties": {
            "summary": {"type": "string", "description": "2-3 sentence overview of directory health"},
            "overallScore": {"type": "string", "enum": ["good", "needs-attention", "critical"]},
            "findings": {
                "type": "array",
                "description": "One entry per issue. Must not be empty if problems exist.",
                "items": {
                    "type": "object",
                    "required": ["severity", "category", "title", "description", "affectedPath", "actualBehavior"],
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                        "category": {
                            "type": "string",
                            "enum": [
                                "missing-data", "low-file-count", "naming-anomaly",
                                "scraper-failure", "filesystem-artifact", "structural-issue",
                                "duplicate-content", "other",
                            ],
                        },
                        "title": {"type": "string"},
                        "description": {"type": "string", "description": "Detailed explanation with specific numbers and examples"},
                        "affectedPath": {"type": "string"},
                        "expectedBehavior": {"type": "string", "description": "What a complete/healthy version would look like, if inferrable"},
                        "actualBehavior": {"type": "string", "description": "What is actually present, with specific counts"},
                    },
                },
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Directory summary builder
# ---------------------------------------------------------------------------

import re

JUNK_PATTERN = re.compile(
    r'@eaDir|\.DS_Store|Thumbs\.db|desktop\.ini|__MACOSX|SynoEAStream|SynoResource',
    re.IGNORECASE,
)


def build_directory_summary(all_items: list[dict], root_path: str) -> dict:
    """Organize raw file listing into a per-folder summary with basic stats."""
    files = [i for i in all_items if i.get("type") == "file"]
    dirs = [i for i in all_items if i.get("type") == "directory"]

    folder_map: dict[str, list[dict]] = {}
    for f in files:
        folder_path = f["path"].rsplit("/", 1)[0] if "/" in f["path"] else root_path
        folder_map.setdefault(folder_path, []).append(f)

    folder_summaries = []
    for folder_path, folder_files in sorted(folder_map.items()):
        names = [f.get("display_name", "") for f in folder_files]
        junk_count = sum(1 for n in names if JUNK_PATTERN.search(n))

        ext_counts: dict[str, int] = {}
        for n in names:
            if JUNK_PATTERN.search(n):
                continue
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else "no-ext"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        folder_summaries.append({
            "path": folder_path,
            "fileCount": len(folder_files),
            "junkCount": junk_count,
            "fileTypes": ext_counts,
            "filenames": names,
        })

    return {
        "rootPath": root_path,
        "totalFiles": len(files),
        "totalDirs": len(dirs),
        "folders": folder_summaries,
    }


def _format_for_claude(summary: dict) -> str:
    """Format directory summary as readable text for Claude."""
    lines = [
        f"Directory: {summary['rootPath']}",
        f"Total: {summary['totalFiles']} files across {summary['totalDirs']} directories",
        "",
    ]

    for folder in summary["folders"]:
        real_count = folder["fileCount"] - folder["junkCount"]
        junk_note = f" (+{folder['junkCount']} junk/artifacts)" if folder["junkCount"] else ""
        lines.append(f"=== {folder['path']} === ({real_count} files{junk_note})")

        if folder["fileTypes"]:
            lines.append(f"  Types: {json.dumps(folder['fileTypes'])}")

        for name in folder["filenames"]:
            lines.append(f"  - {name}")
        lines.append("")

    return "\n".join(lines)


def run_analysis(summary: dict, tier: str = "sonnet") -> dict:
    model_id = "claude-opus-4-6" if tier == "opus" else "claude-sonnet-4-6"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = _format_for_claude(summary)

    response = client.messages.create(
        model=model_id,
        max_tokens=16384,
        system=SYSTEM_PROMPT,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "report_findings"},
        messages=[{"role": "user", "content": user_message}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise RuntimeError(f"Claude did not return tool_use (stop_reason={response.stop_reason})")

    return {
        "content": tool_use.input,
        "model": model_id,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/ping")
async def ping():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/folders")
async def get_folders(path: str = "/"):
    items = await list_folder(path)
    breadcrumbs = build_breadcrumbs(path)
    return {"items": items, "path": path, "breadcrumbs": breadcrumbs}


@app.get("/api/folders/tree")
async def get_folder_tree(path: str = "/", depth: int = 2):
    items = await list_folder(path)
    folders = [i for i in items if i.get("type") == "directory"]
    tree = [{"name": f.get("display_name", ""), "path": f["path"]} for f in folders]
    return {"tree": tree}


class AnalysisRequest(BaseModel):
    path: str
    recursive: bool = True
    maxDepth: int = 5
    tier: str = "sonnet"


@app.post("/api/analysis")
async def start_analysis(req: AnalysisRequest):
    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO analysis_reports (id, path, status, created_at) VALUES (?, ?, 'processing', ?)",
        (report_id, req.path, now),
    )
    conn.commit()
    conn.close()

    asyncio.create_task(_run_analysis_task(report_id, req))
    return {"id": report_id, "status": "processing"}


async def _run_analysis_task(report_id: str, req: AnalysisRequest):
    try:
        depth = req.maxDepth if req.recursive else 1
        all_items = await list_folder_recursive(req.path, depth)
        summary = build_directory_summary(all_items, req.path)
        result = await asyncio.to_thread(run_analysis, summary, req.tier)

        content = result["content"]
        conn = get_db()
        conn.execute(
            """UPDATE analysis_reports
               SET status='complete', completed_at=?, summary=?, overall_score=?,
                   findings=?, recommendations=?, model=?, input_tokens=?, output_tokens=?
               WHERE id=?""",
            (
                datetime.now(timezone.utc).isoformat(),
                content.get("summary"),
                content.get("overallScore"),
                json.dumps(content.get("findings", [])),
                json.dumps(content.get("recommendations", [])),
                result["model"],
                result["input_tokens"],
                result["output_tokens"],
                report_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        conn = get_db()
        conn.execute(
            "UPDATE analysis_reports SET status='error', completed_at=?, error=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), str(exc), report_id),
        )
        conn.commit()
        conn.close()


@app.get("/api/analysis/{report_id}")
async def get_analysis(report_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM analysis_reports WHERE id=?", (report_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _serialize_report(row)


@app.get("/api/analysis/{report_id}/pdf")
async def export_analysis_pdf(report_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM analysis_reports WHERE id=?", (report_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    report = _serialize_report(row)
    if report.get("status") != "complete":
        raise HTTPException(status_code=400, detail="Report is not complete")

    pdf_bytes = _generate_pdf(report)
    safe_name = report["path"].replace("/", "_").replace(" ", "_").strip("_")
    filename = f"analysis_{safe_name}_{report_id[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/analysis")
async def list_analysis_reports():
    conn = get_db()
    rows = conn.execute("SELECT * FROM analysis_reports ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return {"reports": [_serialize_report(r) for r in rows]}


_PDF_CHAR_REPLACEMENTS = {
    "\u2013": "-",
    "\u2014": "--",
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2026": "...",
    "\u2022": "*",
    "\u00a0": " ",
    "\u202f": " ",
    "\u2009": " ",
    "\u200b": "",
    "\u2192": "->",
    "\u2190": "<-",
    "\u2191": "^",
    "\u2193": "v",
}


def _safe(text) -> str:
    """Coerce text to something fpdf2's Latin-1 core fonts can render."""
    if text is None:
        return ""
    s = str(text)
    for src, dst in _PDF_CHAR_REPLACEMENTS.items():
        s = s.replace(src, dst)
    return s.encode("latin-1", "replace").decode("latin-1")


def _generate_pdf(report: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, _safe("File Review Analysis Report"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, _safe(report["path"]), new_x="LMARGIN", new_y="NEXT")

    score = report.get("overallScore", "unknown")
    completed = report.get("completedAt", "")
    if completed:
        try:
            completed = datetime.fromisoformat(completed).strftime("%B %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            pass

    pdf.cell(0, 6, _safe(f"Overall Score: {score.replace('-', ' ').title()}    |    {completed}"), new_x="LMARGIN", new_y="NEXT")
    if report.get("model"):
        pdf.cell(0, 6, _safe(f"Model: {report['model']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if report.get("summary"):
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _safe("Summary"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe(report["summary"]))
        pdf.ln(4)

    findings = report.get("findings", [])
    if findings:
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        findings_sorted = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "info"), 3))

        severity_colors = {
            "critical": (220, 38, 38),
            "warning": (217, 119, 6),
            "info": (37, 99, 235),
        }

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, _safe(f"Findings ({len(findings)})"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for i, finding in enumerate(findings_sorted):
            severity = finding.get("severity", "info")
            r, g, b = severity_colors.get(severity, (100, 100, 100))

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(r, g, b)
            pdf.cell(0, 6, _safe(f"[{severity.upper()}] {finding.get('title', 'Untitled')}"), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(0, 5, _safe(f"Category: {finding.get('category', 'other')}"), new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(0, 4.5, _safe(finding.get("description", "")))

            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(60, 60, 60)
            affected = finding.get("affectedPath", "")
            if affected:
                pdf.cell(0, 5, _safe(f"Path: {affected}"), new_x="LMARGIN", new_y="NEXT")

            expected = finding.get("expectedBehavior", "")
            actual = finding.get("actualBehavior", "")
            if expected:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(60, 60, 60)
                pdf.multi_cell(0, 4.5, _safe(f"Expected: {expected}"))
            if actual:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(60, 60, 60)
                pdf.multi_cell(0, 4.5, _safe(f"Actual: {actual}"))

            pdf.ln(4)

    recommendations = report.get("recommendations", [])
    if recommendations:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, _safe("Recommendations"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        for j, rec in enumerate(recommendations, 1):
            pdf.multi_cell(0, 5, _safe(f"{j}. {rec}"))
            pdf.ln(1)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, _safe("Generated by Madison File Reviews"), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def _serialize_report(row: sqlite3.Row) -> dict:
    d = dict(row)
    result = {
        "id": d["id"],
        "path": d["path"],
        "status": d["status"],
        "createdAt": d["created_at"],
        "completedAt": d.get("completed_at"),
        "summary": d.get("summary"),
        "overallScore": d.get("overall_score"),
        "findings": json.loads(d["findings"]) if d.get("findings") else None,
        "recommendations": json.loads(d["recommendations"]) if d.get("recommendations") else None,
        "error": d.get("error"),
        "model": d.get("model"),
        "inputTokens": d.get("input_tokens"),
        "outputTokens": d.get("output_tokens"),
    }
    return {k: v for k, v in result.items() if v is not None}


# ---------------------------------------------------------------------------
# Serve the React frontend (built static files)
# ---------------------------------------------------------------------------

DIST_DIR = Path(__file__).parent / "dist"
if DIST_DIR.exists() and (DIST_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = DIST_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(DIST_DIR / "index.html"))
