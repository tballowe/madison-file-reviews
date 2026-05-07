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


def _xml_escape(text) -> str:
    """Escape text for use in ReportLab's Paragraph XML markup."""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


def _generate_pdf(report: dict) -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.colors import HexColor, Color
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "ReportTitle", parent=styles["Heading1"], fontSize=18, spaceAfter=4,
    )
    style_path = ParagraphStyle(
        "ReportPath", parent=styles["Normal"], fontSize=10,
        textColor=HexColor("#646464"), spaceAfter=2,
    )
    style_meta = ParagraphStyle(
        "ReportMeta", parent=styles["Normal"], fontSize=10,
        textColor=HexColor("#646464"), spaceAfter=12,
    )
    style_heading = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=12, spaceAfter=6,
    )
    style_body = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=8,
    )
    style_finding_title = ParagraphStyle(
        "FindingTitle", parent=styles["Normal"], fontSize=10,
        leading=13, spaceBefore=4, spaceAfter=2,
    )
    style_finding_detail = ParagraphStyle(
        "FindingDetail", parent=styles["Normal"], fontSize=9,
        leading=12, spaceAfter=2, textColor=HexColor("#282828"),
    )
    style_finding_meta = ParagraphStyle(
        "FindingMeta", parent=styles["Normal"], fontSize=9,
        leading=11, textColor=HexColor("#787878"), spaceAfter=2,
    )
    style_rec = ParagraphStyle(
        "Recommendation", parent=styles["Normal"], fontSize=10,
        leading=14, spaceAfter=4, leftIndent=12,
    )
    style_footer = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8,
        textColor=HexColor("#969696"), spaceBefore=24,
    )

    severity_colors = {
        "critical": "#DC2626",
        "warning": "#D97706",
        "info": "#2563EB",
    }

    story = []

    story.append(Paragraph(_xml_escape("File Review Analysis Report"), style_title))
    story.append(Paragraph(_xml_escape(report["path"]), style_path))

    score = report.get("overallScore", "unknown")
    completed = report.get("completedAt", "")
    if completed:
        try:
            completed = datetime.fromisoformat(completed).strftime("%B %d, %Y at %I:%M %p")
        except (ValueError, TypeError):
            pass

    meta_parts = [f"Overall Score: {score.replace('-', ' ').title()}"]
    if completed:
        meta_parts.append(completed)
    if report.get("model"):
        meta_parts.append(f"Model: {report['model']}")
    story.append(Paragraph(_xml_escape("  |  ".join(meta_parts)), style_meta))

    if report.get("summary"):
        story.append(Paragraph("Summary", style_heading))
        story.append(Paragraph(_xml_escape(report["summary"]), style_body))

    findings = report.get("findings", [])
    if findings:
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        findings_sorted = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "info"), 3))

        story.append(Paragraph(_xml_escape(f"Findings ({len(findings)})"), style_heading))

        for finding in findings_sorted:
            severity = finding.get("severity", "info")
            color = severity_colors.get(severity, "#646464")
            title_text = (
                f'<font color="{color}"><b>[{_xml_escape(severity.upper())}]</b></font> '
                f'<b>{_xml_escape(finding.get("title", "Untitled"))}</b>'
            )
            story.append(Paragraph(title_text, style_finding_title))

            category = finding.get("category", "other")
            story.append(Paragraph(
                f'<i>Category: {_xml_escape(category)}</i>', style_finding_meta,
            ))

            description = finding.get("description", "")
            if description:
                story.append(Paragraph(_xml_escape(description), style_finding_detail))

            affected = finding.get("affectedPath", "")
            if affected:
                story.append(Paragraph(
                    f'<b>Path:</b> {_xml_escape(affected)}', style_finding_meta,
                ))

            expected = finding.get("expectedBehavior", "")
            if expected:
                story.append(Paragraph(
                    f'<b>Expected:</b> {_xml_escape(expected)}', style_finding_detail,
                ))

            actual = finding.get("actualBehavior", "")
            if actual:
                story.append(Paragraph(
                    f'<b>Actual:</b> {_xml_escape(actual)}', style_finding_detail,
                ))

            story.append(Spacer(1, 8))

    recommendations = report.get("recommendations", [])
    if recommendations:
        story.append(Paragraph("Recommendations", style_heading))
        for j, rec in enumerate(recommendations, 1):
            story.append(Paragraph(f"{j}. {_xml_escape(rec)}", style_rec))

    story.append(Paragraph(_xml_escape("Generated by Madison File Reviews"), style_footer))

    doc.build(story)
    return buf.getvalue()


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
