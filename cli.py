"""Command-line interface (argparse). Works completely without the GUI.

Exit codes: 0 success, 1 runtime error (network, database...), 2 invalid input.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from typing import List, Optional

from config import APP_NAME, APP_TAGLINE, APP_VERSION, CATEGORIES, SORT_OPTIONS, Config
from errors import FilterError, NewsPulseError
from filters import ArticleFilter
from logger import get_logger, setup_logging
from models import Article
from services import NewsService
from utils import format_datetime, truncate

log = get_logger("cli")

EPILOG = """\
examples:
  python main.py --fetch                      fetch the latest headlines
  python main.py --demo --fetch               load clearly-labelled DEMO data (no API key needed)
  python main.py --search "technology"        search stored articles
  python main.py --search "AI" --online       also query NewsAPI's archive first
  python main.py --source BBC                 articles from sources matching "BBC"
  python main.py --date 2026-10-31            articles published on that day (UTC)
  python main.py --category sports --from-date 2026-10-01 --to-date 2026-10-31
  python main.py --export csv                 export everything to exports/
  python main.py --search ai --export excel   export only the filtered results
  python main.py --list-saved                 show bookmarked articles
  python main.py --save 12 --note "read later"
  python main.py --stats                      collection statistics
  python main.py                              (no arguments) launch the GUI
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python main.py",
        description=f"{APP_NAME} - {APP_TAGLINE}: fetch, search, save and export news.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_argument_group("fetching")
    g.add_argument("--fetch", action="store_true", help="fetch the latest headlines and store them")
    g.add_argument("--online", action="store_true", help="with --search: query NewsAPI's archive first")
    g.add_argument("--refresh-sources", action="store_true", help="download the list of news sources from NewsAPI")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true",
                      help="switch to DEMO mode (labelled sample data, no API key needed); stays on until --live")
    mode.add_argument("--live", action="store_true", help="switch back to live mode (real NewsAPI data)")

    g = p.add_argument_group("searching & filtering (combinable)")
    g.add_argument("--search", metavar="TEXT", help="keyword(s) in title, description or source")
    g.add_argument("--source", metavar="NAME", help="source name (partial match, e.g. BBC)")
    g.add_argument("--category", metavar="NAME", help=f"one of: {', '.join(CATEGORIES)}")
    g.add_argument("--date", metavar="YYYY-MM-DD", help="articles published on this day (also: today, yesterday)")
    g.add_argument("--from-date", metavar="YYYY-MM-DD", help="published on or after this date")
    g.add_argument("--to-date", metavar="YYYY-MM-DD", help="published on or before this date")
    g.add_argument("--sort", choices=list(SORT_OPTIONS), default="newest", help="sort order (default: newest)")
    g.add_argument("--limit", type=int, default=20, metavar="N", help="articles per page (default 20)")
    g.add_argument("--page", type=int, default=1, metavar="N", help="page number (default 1)")

    g = p.add_argument_group("saved articles")
    g.add_argument("--list-saved", action="store_true", help="list saved (bookmarked) articles")
    g.add_argument("--save", type=int, metavar="ID", help="save an article by its ID")
    g.add_argument("--note", metavar="TEXT", help="optional note to attach when using --save")
    g.add_argument("--unsave", type=int, metavar="ID", help="remove an article from the saved list")

    g = p.add_argument_group("articles")
    g.add_argument("--show", type=int, metavar="ID", help="show full details of one article")
    g.add_argument("--delete", type=int, metavar="ID", help="delete an article from the database")
    g.add_argument("--enrich", type=int, metavar="ID", help="read the article's web page to fill in a missing image/description")

    g = p.add_argument_group("export & analytics")
    g.add_argument("--export", choices=["csv", "excel", "json"], help="export (filtered) articles to exports/")
    g.add_argument("--output", metavar="NAME", help="file name for --export (extension added automatically)")
    g.add_argument("--stats", action="store_true", help="print collection statistics")
    g.add_argument("--sources", action="store_true", help="list known news sources with article counts")
    g.add_argument("--chart", choices=["source", "category", "daily"], help="save an analytics chart as PNG")

    g = p.add_argument_group("maintenance")
    g.add_argument("--backup", action="store_true", help="create a database backup in database/backups/")
    g.add_argument("--gui", action="store_true", help="launch the graphical interface")
    g.add_argument("--verbose", action="store_true", help="also print log messages to the console")
    g.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return p


# ------------------------------------------------------------ rendering --
def _print_article(a: Article, width: int) -> None:
    flags = (" [SAVED]" if a.is_saved else "") + (" [DEMO]" if a.is_demo and not a.title.startswith("[DEMO]") else "")
    print(f"[{a.id}] {format_datetime(a.published_at)} | {a.source_name} | {a.category}{flags}")
    print(textwrap.fill(a.title, width, initial_indent="    ", subsequent_indent="    "))
    print(f"    {a.url}")
    if a.note:
        print(f"    Note: {a.note}")


def _print_details(a: Article, width: int) -> None:
    print(f"ID:          {a.id}")
    print(f"Title:       {a.title}")
    print(f"Source:      {a.source_name}")
    print(f"Category:    {a.category}")
    print(f"Published:   {format_datetime(a.published_at)}")
    print(f"Author:      {a.author or '-'}")
    print(f"Saved:       {'yes' if a.is_saved else 'no'}{(' - ' + a.note) if a.note else ''}")
    print(f"URL:         {a.url}")
    print(f"Image:       {a.image_url or '-'}")
    print("Description:")
    print(textwrap.fill(a.description or "-", width, initial_indent="  ", subsequent_indent="  "))


def _width() -> int:
    return max(60, min(110, shutil.get_terminal_size((100, 24)).columns - 2))


# ----------------------------------------------------------------- main --
def run(argv: Optional[List[str]] = None, config: Optional[Config] = None,
        service: Optional[NewsService] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    config = config or (service.config if service else Config())
    setup_logging(config.paths.logs_dir, config.log_level, console=args.verbose)
    log.info("CLI invoked: %s", " ".join(argv or sys.argv[1:]))

    if args.limit < 1 or args.limit > 500:
        parser.error("--limit must be between 1 and 500")
    if args.page < 1:
        parser.error("--page must be 1 or greater")
    if args.date and (args.from_date or args.to_date):
        parser.error("use either --date or --from-date/--to-date, not both")

    wants_list = any([args.search, args.source, args.category, args.date,
                      args.from_date, args.to_date, args.list_saved])
    actions = any([args.demo, args.live, args.fetch, args.refresh_sources, args.save is not None, args.unsave is not None,
                   args.delete is not None, args.enrich is not None, args.show is not None, args.stats,
                   args.sources, args.chart, args.backup, args.export, wants_list])
    if not actions:
        parser.print_help()
        return 0

    try:
        service = service or NewsService(config)
        return _execute(args, service)
    except FilterError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    except NewsPulseError as exc:
        log.error("Command failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:       # e.g. output piped into `head`
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # last-resort guard: never show a raw traceback to the user
        log.exception("Unexpected error")
        print(f"Unexpected error: {exc}\nDetails were written to {config.paths.logs_dir / 'newspulse.log'}",
              file=sys.stderr)
        return 1


def _execute(args: argparse.Namespace, svc: NewsService) -> int:
    width = _width()
    if args.demo:
        svc.prefs.set("demo_mode", True)
        print("Demo mode enabled (saved). Run `python main.py --live` to go back to real news.")
    if args.live:
        svc.prefs.set("demo_mode", False)
        print("Live mode enabled (saved).")
    if svc.demo_mode:
        print("*** DEMO MODE: sample data only - NOT real news. (switch back with --live) ***")

    if args.backup:
        print(f"Database backup created: {svc.backup_database()}")

    if args.refresh_sources:
        print(f"Stored {svc.refresh_sources()} news sources.")

    if args.fetch:
        if svc.needs_setup:
            print("NewsPulse needs a NewsAPI key to fetch live news.\n"
                  "  1. Get a free key at https://newsapi.org/register\n"
                  "  2. Put it in a .env file:  NEWSAPI_KEY=your_key_here\n"
                  "  3. Run this command again.\n"
                  "Or try the app now with labelled sample data:  python main.py --demo --fetch",
                  file=sys.stderr)
            return 1
        print("Fetching news…")
        result = svc.fetch_latest(progress=lambda i, n, msg: print(f"  [{i}/{n}] {msg}") if i < n else None)
        print(result.summary())

    if args.save is not None:
        svc.save_article(args.save, args.note or "")
        print(f"Saved article {args.save}.")
    if args.unsave is not None:
        svc.unsave_article(args.unsave)
        print(f"Removed article {args.unsave} from saved articles.")
    if args.delete is not None:
        svc.delete_article(args.delete)
        print(f"Deleted article {args.delete}.")
    if args.enrich is not None:
        article = svc.enrich_article(args.enrich)
        print(f"Updated article {article.id}. Image: {article.image_url or 'none found'}")

    if args.show is not None:
        article = svc.get_article(args.show)
        if not article:
            print(f"Error: article {args.show} not found.", file=sys.stderr)
            return 1
        _print_details(article, width)

    if args.sources:
        sources = svc.list_sources()
        if not sources:
            print("No sources stored yet. Run --fetch (or --refresh-sources) first.")
        for s in sources:
            print(f"{s['article_count']:>5}  {s['name']}" + (f"  ({s['api_id']})" if s["api_id"] else ""))

    if args.stats:
        _print_stats(svc)

    if args.chart:
        print(f"Chart saved: {svc.chart(args.chart)}")

    wants_list = any([args.search, args.source, args.category, args.date,
                      args.from_date, args.to_date, args.list_saved])
    flt = None
    if wants_list or args.export:
        flt = ArticleFilter.from_inputs(
            keyword=args.search or "", source=args.source or "", category=args.category or "",
            date_from=args.date or args.from_date or "", date_to=args.date or args.to_date or "",
            sort=args.sort, saved_only=args.list_saved)

    if args.search and args.online:
        print(f"Searching NewsAPI for '{args.search}'…")
        d_from = flt.date_from if flt else None
        d_to = flt.date_to if flt else None
        print(svc.search_online(args.search, d_from, d_to).summary())

    if args.export:
        path, count = svc.export(args.export, flt, filename=args.output)
        print(f"Exported {count} article{'s' if count != 1 else ''} to {path}")
    elif wants_list:
        page = svc.query(flt, args.page, args.limit)
        if page.total == 0:
            print("No articles match. Try different filters, or run --fetch first.")
        else:
            print(f"{page.total} article(s) - page {page.page} of {page.pages}\n")
            for article in page.items:
                _print_article(article, width)
            if page.page < page.pages:
                print(f"\nMore results: add --page {page.page + 1}")
    return 0


def _print_stats(svc: NewsService) -> None:
    data = svc.dashboard()
    c = data["counts"]
    print(f"Total articles:     {c['total']}")
    print(f"Published today:    {c['today']}  (UTC)")
    print(f"News sources:       {c['sources']}")
    print(f"Saved articles:     {c['saved']}")
    last = data["last_fetch"]
    print(f"Last fetch:         {format_datetime(last['started_at']) if last else 'never'}")
    print("\nBy category:")
    for name, n in data["categories"] or [("(none)", 0)]:
        print(f"  {name:<15}{n}")
    print("\nTop sources:")
    for name, n in svc.db.count_by_source(svc.demo_mode, 5) or [("(none)", 0)]:
        print(f"  {truncate(name, 30):<32}{n}")
    print("\nTrending keywords: " + (", ".join(f"{w} ({n})" for w, n in data["keywords"][:10]) or "-"))
