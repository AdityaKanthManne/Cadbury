# Desktop Butler

A floating butler that lives on your Mac desktop and, at **8:00 AM and 8:00 PM Eastern**, collects new
quant-finance and AI/ML papers, news and market data, ranks them against your interests, and presents a
short briefing.

## Sources (all through free Python libraries)

| What | Library | Key needed |
| --- | --- | --- |
| arXiv papers (q-fin, ML x finance, LLMs, time series...) | `arxiv` | no |
| Federal Reserve press releases and speeches, Jane Street blog, OpenAI, Google DeepMind, Google Research, Hugging Face, BAIR and NVIDIA blogs | `feedparser` | no |
| World news headlines (quant funds, the Fed, markets, AI, quant firms) | `gdeltdoc` (GDELT) | no |
| Hacker News stories with 60+ points | `httpx` (Algolia HN API) | no |
| S&P 500, Nasdaq, VIX, 10-year yield, dollar index, gold, oil, Bitcoin | `yfinance` (Yahoo Finance, delayed, personal use) | no |
| CPI, unemployment, fed funds, 10-year yield, 10y-2y spread | `fredapi` | free [FRED key](https://fred.stlouisfed.org/docs/api/api_key.html) |

All of them are configured in `configs/user_profile.yaml` (`sources:`), where you can add feeds, change
news queries or tickers, or switch a source off. One failing source never stops the others; failures show
under Settings and diagnostics. Big market moves (S&P 500 ±1.5%, VIX ±15%, 10-year ±10 bp...) become
briefing items. The same story from several outlets is merged into one item that lists the other outlets.
News from GDELT is headline-only: the butler says so and links to the publisher.

Built from the *Project DUCK* spec, with your butler sprite sheet in place of the duck.

## Install on your Mac

```bash
cd "/Users/adityakanthmanne/Downloads/Github Projects/Cadbury"
bash scripts/setup_mac.sh
```

The script checks your tools (Xcode command line tools, Python 3.10+, Node 18+, Rust), installs the
backend into `.venv`, runs the tests, does one live arXiv fetch, builds `Desktop Butler.app`, installs it
in Applications and opens it. Nothing needs `sudo`.

To keep him running after restarts, right-click the butler and turn on **Start at login**.

## Using it

| Do this | Get this |
| --- | --- |
| Click the butler | Opens the briefing |
| Drag the butler | Moves him; the position is remembered |
| Hover | A one-line status (next briefing, top pick, or what went wrong) |
| Right-click | Fetch now, quiet mode, keep on top, let him roam, start at login, hide, quit |
| Menu-bar icon | Show butler, open briefing, quit |

What his pose means: **phone** = fetching from arXiv · **silver tray + number** = new briefing waiting ·
**pointing** = a paper scored above 80 · **hand on chin** = last fetch failed (retries every 30 min) ·
**armchair** = night (11 PM–7 AM) · otherwise standing idle.

If the Mac is asleep at 8:00, he catches up within 15 minutes of waking.

Left alone, he roams (in the spirit of Desktop Goose, minus the chaos): he walks around your screen,
reads the paper, dusts, naps in the armchair in the evening, and when there are papers you haven't
read he walks to the middle of the screen, presents his tray and leaves a **note** with the paper's
title and why it matters (at most three on screen). "Read it" opens the briefing; × dismisses it.
He pauses while your cursor is on him, never touches your mouse or keyboard, and stops roaming in
quiet mode, with "Let him roam" off, or when reduced motion is on.

## Sections

The dashboard is organised into four sections (Today's briefing groups items the same way):

| Section | What goes there |
| --- | --- |
| Market | price table and macro data, big price moves, Federal Reserve releases and speeches, market & macro news |
| Research | arXiv papers |
| News | quant firms, funds, careers and other industry stories |
| Tech developments | AI-lab and engineering blogs, Hacker News, AI and infrastructure news |

The interest areas in `configs/user_profile.yaml` still decide how relevant each item is; sections only
decide where it is shown (see `services/butler/butler/sections.py`).

## How papers are ranked

`S = 0.30·Relevance + 0.20·Source quality + 0.15·Novelty + 0.15·Impact + 0.10·Freshness + 0.10·Learning value`

Source quality and freshness depend on the kind of item: Fed releases 0.9, quant-firm blogs 0.8, AI-lab
blogs 0.75, top news outlets 0.7 (other outlets 0.5, more for wider coverage), Hacker News by points.
News fades in about a day, papers in three, firm blogs in five. A briefing holds at most 6 papers,
6 news items and 2 Hacker News stories.

These are the spec's heuristic starting weights, not a fitted model. Relevance is currently keyword/phrase
matching against `configs/user_profile.yaml` (weights 25/25/20/15/10/5 across Quant Finance, AI/ML,
Quant + AI, Markets & Macro, Careers, Infra). Every paper shows its per-signal breakdown and a plain
reason. Papers that barely match your interests are halved so freshness can't carry them. The briefing
takes the top 10, at most 4 per area. Papers you mark "Not for me" are left out of future briefings.

Edit `configs/user_profile.yaml` to change weights, keywords or the arXiv searches, then quit and reopen the app.

## Layout

```
apps/desktop/            Tauri 2 + React + TypeScript app (butler window + dashboard)
  public/butler/         animation strips cut from the sprite sheet (tools/cut_sprites.py)
  src-tauri/             Rust shell: windows, menu-bar icon, starts & supervises the backend
services/butler/         Python backend (FastAPI on 127.0.0.1:8765, APScheduler, SQLite)
  butler/collector.py    arXiv ingestion via the `arxiv` library
  butler/ranking.py      six-signal scoring + explanations
  butler/service.py      briefing pipeline, 8 AM / 8 PM schedule, catch-up after sleep
configs/user_profile.yaml  your interests and arXiv searches
tests/                   pytest suite (arXiv responses simulated at the HTTP layer)
scripts/setup_mac.sh     one-command Mac install
```

Your data lives outside the repo, in `~/Library/Application Support/DesktopButler/`
(`butler.db`, `butler.log`). Backend start-up output goes to `~/Library/Logs/com.cadbury.desktopbutler/`.

## Development

```bash
.venv/bin/python -m pytest tests -q                  # backend tests
python tests/demo_server.py                          # backend with synthetic papers, no network
cd apps/desktop && npm run tauri dev                 # app with hot reload
BUTLER_BEHAVIOR_FAST=1 npm run tauri dev             # same, with the butler 6x busier
```

The app starts `services/butler/butler_main.py` with `.venv/bin/python` from the folder it was built in.
If you move the Cadbury folder, rebuild, or set `BUTLER_REPO` / `BUTLER_PYTHON`.

## Status

Done (spec Phase 1, plus arXiv ingestion, baseline ranking and scheduling):
floating animated butler that roams the screen and leaves notes about unread papers (transparent,
always on top, draggable, remembers position, hover summary,
context menu, quiet mode, opt-in autostart, menu-bar icon, reduced-motion support); dashboard with
briefing, per-area lists, search, sort, saved papers, relevant / not-for-me feedback, score explanations,
settings and diagnostics; arXiv collection with dedupe and per-search failure isolation; local SQLite.

Also done: RSS (Fed, quant firm and AI-lab blogs), GDELT news, Hacker News, market prices and moves,
FRED macro, story clustering, Markets view.

Not yet: GitHub and SEC EDGAR sources, sentence-transformer relevance, Ollama summaries
and "Explain this paper", learned ranking from your feedback, evaluation set and metrics, signed
release builds.
