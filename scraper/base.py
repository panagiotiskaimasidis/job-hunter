"""Abstract base class every job-board scraper must implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator
import logging

logger = logging.getLogger(__name__)


@dataclass
class JobPosting:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    salary: str = ""
    job_type: str = ""          # full-time, contract, etc.
    posted_date: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    job_id: str = ""            # unique hash set by runner

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "JobPosting":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BaseJobScraper(ABC):
    """Each subclass scrapes one job board."""

    source_name: str = "unknown"

    def __init__(self, delay_seconds: float = 1.0, max_jobs: int = 15):
        self.delay = delay_seconds
        self.max_jobs = max_jobs

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """
        Return job stubs (title, company, url — NO description) quickly.
        The runner fetches descriptions in parallel afterwards.
        Subclasses should override this for best performance.
        Falls back to safe_search() for boards that don't split the two steps.
        """
        return self.safe_search(query, location)

    def fetch_description(self, url: str) -> str:
        """Fetch the full description for a single job URL. Override in subclasses."""
        return ""

    @abstractmethod
    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        """Yield fully populated JobPosting objects (legacy path)."""

    def safe_search(self, query: str, location: str) -> list[JobPosting]:
        """Wraps search() with error handling so one board failure doesn't crash the pipeline."""
        results = []
        try:
            for posting in self.search(query, location):
                results.append(posting)
                if len(results) >= self.max_jobs:
                    break
        except Exception as exc:
            logger.error("[%s] search('%s', '%s') failed: %s", self.source_name, query, location, exc)
        return results
