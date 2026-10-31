# NewsPulse – Smart News Aggregator

NewsPulse collects headlines from many publishers into one searchable library on your own computer.
It has a modern desktop app **and** a full command-line interface; both use the same code and the
same SQLite database, and either one works without the other.

- Fetch top headlines by country and category, or search NewsAPI's archive
- Filter by keyword, source, category and date – all filters combine
- Save articles with personal notes, open originals in your browser
- Never store the same article twice (URL-based de-duplication)
- Charts, trending keywords and statistics
- Export the filtered view to CSV, Excel or JSON
- A clearly labelled **demo mode** when you have no API key – sample data is never presented as real news

## Screenshots

> Screenshots are not included yet. After running the app, save PNGs into `docs/screenshots/`
> and replace this note with image links, for example:
>
> ```markdown
> ![Dashboard](docs/screenshots/dashboard.png)
> ![All News](docs/screenshots/all-news.png)
> ![Analytics](docs/screenshots/analytics.png)
> ```
>
> Suggested shots: Dashboard, All News, Search with filters, Analytics, Settings.

## Technology stack

| Purpose | Library |
|---|---|
| GUI | CustomTkinter (on top of Tk) |
| News data | NewsAPI.org via `requests` |
| Page metadata (image/description of an article) | BeautifulSoup |
| Storage | SQLite (`sqlite3`, standard library) |
| Data processing | pandas |
| Excel export | openpyxl |
| Charts | Matplotlib |
| Secrets / config | python-dotenv (`.env`) |
| Tests | `unittest` (standard library) |

## Installation

Requires **Python 3.11 or newer** (developed and tested on 3.12).

```bash
git clone https://github.com/your-username/NewsPulse.git
cd NewsPulse

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
```

**Linux:** Tk is a separate system package. If you see *"No module named tkinter"*:

```bash
sudo apt install python3-tk        # Debian / Ubuntu
sudo dnf install python3-tkinter   # Fedora
```

The command-line interface does not need Tk or CustomTkinter.

## API key setup

1. Create a free account at <https://newsapi.org/register> and copy your API key.
2. Either enter it in the app (**Settings → NewsAPI key → Test connection → Save key**), or create the file yourself:

   ```bash
   cp .env.example .env
   # then edit .env:  NEWSAPI_KEY=your_real_key
   ```

The key lives only in `.env`, which is excluded from Git. It is never written to the database or the logs,
and the app only ever shows its last four characters.

> Free NewsAPI plans have limits (a daily request quota, delayed articles and a limited search history).
> Check <https://newsapi.org/pricing> for the current terms. NewsPulse reports quota and key errors in plain language.

**No key?** Use demo mode – `python main.py --demo`, or *Use demo mode* in the app. Demo articles start with
`[DEMO]`, point to `example.com`, are badged **DEMO** everywhere, are marked in exported files, and are kept
completely separate from live news.

## Run the GUI

```bash
python main.py            # or: python main.py --gui
```

| Page | What it does |
|---|---|
| Dashboard | Totals, today's headlines, recent news, trending keywords (click one to search), category chart |
| All News | Paginated list with keyword / source / category / date filters and sorting |
| Search News | Same filters, plus **Search NewsAPI online** to pull older results into your library |
| Categories | One-click category browsing with live counts |
| Saved Articles | Your bookmarks and notes; export them in one click |
| News Sources | Publishers with article counts; *View articles* filters All News; refresh the full NewsAPI directory |
| Export Data | Pick filters + format, see how many articles will be exported, manage past exports |
| Analytics | Articles by source, by category and per day (7/14/30 days); save any chart as PNG |
| Settings | API key, demo mode, country, categories, page sizes, light/dark theme, backup and cleanup tools |
| About | Version, file locations, credits, shortcuts |

Shortcuts: **F5** refresh · **Ctrl+1 … Ctrl+9, Ctrl+0** jump to a page.
Network work runs in the background with a progress indicator, so the window never freezes.

## Run the CLI

```bash
python main.py --help
```

```bash
python main.py --demo                          # switch to labelled demo data (no key needed)
python main.py --live                          # switch back to real news
python main.py --fetch                         # fetch the latest headlines
python main.py --search "technology"           # keyword search in stored articles
python main.py --search "ai" --online          # search NewsAPI's archive first, then list
python main.py --source BBC                    # partial source name
python main.py --category science --limit 5
python main.py --date 2026-10-31               # one day (also: today, yesterday)
python main.py --from-date 2026-10-01 --to-date 2026-10-31 --sort oldest
python main.py --search sample --category health --page 2     # filters combine

python main.py --save 12 --note "read later"   # bookmark (IDs are shown in listings)
python main.py --list-saved
python main.py --unsave 12
python main.py --show 12                       # full details
python main.py --enrich 12                     # read the original page for a missing image/summary

python main.py --export csv                    # also: excel, json
python main.py --export excel --search python --output python-news   # export a filtered view
python main.py --stats                         # totals, categories, top sources
python main.py --sources
python main.py --chart category                # saves a PNG (source | category | daily)
python main.py --backup
python main.py --verbose                       # log to the console as well
```

Exit codes: `0` success · `1` runtime error (no key, network, nothing to export …) · `2` invalid input.

## Database

SQLite file: `database/newspulse.db`, created automatically on first run and kept between sessions.

| Table | Contents |
|---|---|
| `articles` | One row per article (`url`, unique normalised `url_key`, title, description, image, published time, category, source, demo flag) |
| `sources` | Publishers (name is unique, case-insensitive) |
| `saved_articles` | Bookmarks (+ note), cascade-deleted with their article |
| `fetch_log` | One row per fetch, used for "last update" and statistics |
| `settings` | Your preferences |

**Duplicate detection:** every article URL is normalised before insertion – scheme and host are lower-cased,
`www.` and trailing slashes are removed, tracking parameters (`utm_*`, `fbclid`, …) are dropped, and query
parameters are sorted. The normalised key is `UNIQUE`, so `https://www.site.com/a/?utm_source=x` and
`https://site.com/a` are the same article. All queries are parameterised (no string-built SQL).

Back up from **Settings → Back up database** or `python main.py --backup` (copies go to `database/backups/`).

## Export

**Export Data** page or `--export csv|excel|json`. Exports contain exactly the articles matching your
current filters (or only saved articles) and are written to `exports/`. Existing files are never overwritten;
a numeric suffix is added instead. Excel exports have a styled header, frozen top row and auto-width columns, and
text cells are protected against spreadsheet formula injection. JSON exports include the filters used and
a timestamp. Demo exports are labelled in the file name and inside the file.

## Project structure

```
NewsPulse/
├── main.py            entry point: no arguments -> GUI, otherwise CLI
├── cli.py             argparse command-line interface
├── services.py        application layer used by BOTH front-ends (no GUI code)
├── config.py          paths, .env / API-key handling, constants
├── database.py        SQLite schema and all queries
├── news_fetcher.py    NewsAPI client (retries, error mapping)
├── scraper.py         polite page-metadata reader (BeautifulSoup)
├── filters.py         validated search/filter object -> parameterised SQL
├── exporter.py        CSV / Excel / JSON writers
├── analytics.py       pandas frames + Matplotlib figures
├── demo_data.py       clearly labelled sample articles
├── models.py  errors.py  logger.py  utils.py
├── ui/                CustomTkinter front-end (app shell, sidebar, pages, reusable widgets)
├── tests/             automated tests
├── assets/  database/  exports/  logs/
├── requirements.txt  .env.example  .gitignore
```

GUI code never contains business logic: pages call `services.NewsService`, which is what the CLI uses too.

## Testing

```bash
python -m unittest discover -s tests -t . -v
```

- **Unit/integration tests** cover the database (including duplicate detection), filters, the NewsAPI client
  (bad key, rate limit, timeouts, offline), exports (files are re-opened and checked), the scraper, services, and the CLI.
- **`test_gui_smoke.py`** runs the real app window, pages, service layer, database and background threads on a
  strict *fake* toolkit (`tests/fake_gui.py`), so it works on any machine, including headless servers. It
  "clicks" through every page and workflow. It verifies behaviour and wiring, **not** pixels or real CustomTkinter arguments.
- **`test_gui_real.py`** opens the real window and visits every page. It is skipped automatically when Tk, CustomTkinter or a
  display is missing. On a headless Linux machine: `xvfb-run -a python -m unittest tests.test_gui_real -v`.

No test calls the real NewsAPI (a simulated HTTP session is used), so the suite needs no key and no internet.

## Logging and troubleshooting

Logs are written to `logs/newspulse.log` (rotating, 1 MB × 3). Set `NEWSPULSE_LOG_LEVEL=DEBUG` for more detail,
or use `--verbose` on the CLI.

| Problem | Fix |
|---|---|
| *"needs customtkinter and Tk"* | `pip install -r requirements.txt`; on Linux also install `python3-tk` |
| *"NewsAPI rejected your API key"* | Settings → Test connection; re-copy the key from newsapi.org/account |
| *"request limit reached"* | Wait for the daily quota to reset, or use demo mode |
| *"Cannot reach NewsAPI"* | Check your internet connection / proxy; saved articles remain available offline |
| Window opens too small/large | Display scaling is handled by CustomTkinter; try another scaling setting in your OS |

## Credits and licence

Headlines are provided by [NewsAPI.org](https://newsapi.org). Article text and images belong to their publishers;
NewsPulse stores headlines and short summaries and links back to the original page.
Add a `LICENSE` file of your choice before publishing (MIT is a common option for student projects).
