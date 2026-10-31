"""Export articles to CSV, Excel (.xlsx) or JSON."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from errors import ExportError
from logger import get_logger
from models import Article
from utils import utc_now

log = get_logger("exporter")

FORMATS = {"csv": ".csv", "excel": ".xlsx", "xlsx": ".xlsx", "json": ".json"}
COLUMNS = [
    ("id", "ID"), ("title", "Title"), ("source", "Source"), ("category", "Category"),
    ("published_at", "Published (UTC)"), ("description", "Description"), ("author", "Author"),
    ("url", "URL"), ("image_url", "Image URL"), ("saved", "Saved"), ("note", "Note"),
    ("demo", "Demo data"),
]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _record(a: Article) -> Dict[str, Any]:
    return {"id": a.id, "title": a.title, "source": a.source_name, "category": a.category,
            "published_at": a.published_at, "description": a.description, "author": a.author,
            "url": a.url, "image_url": a.image_url, "saved": "yes" if a.is_saved else "no",
            "note": a.note, "demo": "yes" if a.is_demo else "no"}


def _safe_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula injection (OWASP) in text cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _unique_path(folder: Path, stem: str, suffix: str) -> Path:
    path = folder / f"{stem}{suffix}"
    counter = 2
    while path.exists():
        path = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return path


def export_articles(articles: Sequence[Article], fmt: str, exports_dir: Path,
                    filters_description: str = "", demo: bool = False,
                    filename: Optional[str] = None) -> Path:
    """Write ``articles`` to ``exports_dir`` and return the file path."""
    fmt = (fmt or "").lower().strip()
    if fmt not in FORMATS:
        raise ExportError(f"Unsupported export format '{fmt}'. Choose csv, excel or json.")
    if not articles:
        raise ExportError("There are no articles to export - adjust your filters or fetch some news first.")

    # Honest labelling: a file that contains ANY sample article is marked as demo data,
    # even when the caller (e.g. a "saved only" export made in live mode) did not say so.
    demo = demo or any(a.is_demo for a in articles)

    exports_dir = Path(exports_dir)
    try:
        exports_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%d_%H%M%S")
        default_stem = f"newspulse_{'DEMO_' if demo else ''}news_{stamp}"
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", filename) if filename else default_stem
        suffix = FORMATS[fmt]
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
        path = _unique_path(exports_dir, stem, suffix)
        records = [_record(a) for a in articles]

        if fmt == "json":
            payload = {
                "generated_at": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "application": "NewsPulse",
                "demo_data": demo,
                "filters": filters_description,
                "count": len(records),
                "articles": records,
            }
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        elif fmt == "csv":
            with path.open("w", newline="", encoding="utf-8-sig") as fh:   # BOM: Excel-friendly
                writer = csv.DictWriter(fh, fieldnames=[c[0] for c in COLUMNS], extrasaction="ignore")
                fh.write(",".join(c[1] for c in COLUMNS) + "\r\n")
                for rec in records:
                    writer.writerow({k: _safe_cell(v) for k, v in rec.items()})
        else:
            _write_excel(path, records, filters_description, demo)
    except OSError as exc:
        raise ExportError(f"Could not write the export file: {exc}") from exc
    log.info("Exported %d articles to %s", len(records), path)
    return path


def _write_excel(path: Path, records: List[Dict[str, Any]], filters_description: str, demo: bool) -> None:
    frame = pd.DataFrame([{label: _safe_cell(rec[key]) for key, label in COLUMNS} for rec in records])
    info = pd.DataFrame({
        "Property": ["Application", "Generated (UTC)", "Articles", "Demo data", "Filters"],
        "Value": ["NewsPulse", utc_now().strftime("%Y-%m-%d %H:%M:%S"), len(records),
                  "YES - sample data, not real news" if demo else "no", filters_description or "none"],
    })
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Articles", index=False)
        info.to_excel(writer, sheet_name="Export info", index=False)
        sheet = writer.sheets["Articles"]
        header_fill = PatternFill("solid", fgColor="5B3FD9")
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        widths = {"ID": 7, "Title": 60, "Source": 22, "Category": 14, "Published (UTC)": 22,
                  "Description": 70, "Author": 22, "URL": 50, "Image URL": 30, "Saved": 8,
                  "Note": 30, "Demo data": 11}
        for idx, (_, label) in enumerate(COLUMNS, start=1):
            sheet.column_dimensions[get_column_letter(idx)].width = widths[label]
        url_col = [label for _, label in COLUMNS].index("URL") + 1
        for row in range(2, sheet.max_row + 1):
            cell = sheet.cell(row=row, column=url_col)
            if isinstance(cell.value, str) and cell.value.startswith("http"):
                cell.hyperlink = cell.value
                cell.font = Font(color="2563EB", underline="single")
            sheet.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
        info_sheet = writer.sheets["Export info"]
        info_sheet.column_dimensions["A"].width = 20
        info_sheet.column_dimensions["B"].width = 70
        for cell in info_sheet[1]:
            cell.font = Font(bold=True)
