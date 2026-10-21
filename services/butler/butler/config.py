"""Settings and interest profile."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = REPO_ROOT / "configs" / "user_profile.yaml"


def default_data_dir() -> Path:
    """Personal data lives outside the git repo (spec: never commit local DBs)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DesktopButler"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "DesktopButler"
    return Path.home() / ".local" / "share" / "desktop-butler"


@dataclass
class Area:
    key: str
    label: str
    weight: float
    keywords: List[str]


@dataclass
class ArxivSearchSpec:
    name: str
    query: str
    max_results: int = 30


@dataclass
class Profile:
    owner: str
    areas: Dict[str, Area]
    searches: List[ArxivSearchSpec]
    briefing_size: int = 10
    max_per_area: int = 4
    alert_threshold: float = 80.0
    max_per_kind: Dict[str, int] = field(default_factory=dict)
    sources: Dict = field(default_factory=dict)  # raw config for rss / gdelt / hackernews / markets / fred

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Profile":
        path = Path(path or os.environ.get("BUTLER_PROFILE", DEFAULT_PROFILE))
        raw = yaml.safe_load(path.read_text())
        areas = {
            key: Area(key=key, label=a.get("label", key), weight=float(a.get("weight", 0)),
                      keywords=[str(k) for k in a.get("keywords", [])])
            for key, a in (raw.get("areas") or {}).items()
        }
        searches = [
            ArxivSearchSpec(name=s["name"], query=" ".join(str(s["query"]).split()),
                            max_results=int(s.get("max_results", 30)))
            for s in raw.get("arxiv_searches") or []
        ]
        b = raw.get("briefing") or {}
        return cls(
            owner=raw.get("owner", ""),
            areas=areas,
            searches=searches,
            briefing_size=int(b.get("size", 10)),
            max_per_area=int(b.get("max_per_area", 4)),
            alert_threshold=float(b.get("alert_threshold", 80)),
            max_per_kind={k: int(v) for k, v in {
                "papers": b.get("max_papers"), "news": b.get("max_news"),
                "discussion": b.get("max_discussions")}.items() if v is not None},
            sources=raw.get("sources") or {},
        )


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BUTLER_DATA_DIR", default_data_dir())))
    host: str = "127.0.0.1"  # loopback only (spec §11)
    port: int = int(os.environ.get("BUTLER_PORT", "8765"))
    timezone: str = os.environ.get("BUTLER_TZ", "America/New_York")
    briefing_hours: tuple = (8, 20)  # 8 AM and 8 PM local (Eastern)
    scheduler_enabled: bool = os.environ.get("BUTLER_SCHEDULER", "1") != "0"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "butler.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "butler.log"
