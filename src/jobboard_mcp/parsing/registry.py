from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Optional, List, Tuple

from bs4 import BeautifulSoup  # type: ignore

from .models import ParsedJob


@dataclass
class DetectionResult:
    score: int
    reason: str


class Parser(Protocol):
    name: str

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        ...

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        ...


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: List[Parser] = []

    def register(self, parser: Parser) -> None:
        self._parsers.append(parser)

    def choose(self, url: str, doc: BeautifulSoup) -> Tuple[Parser, DetectionResult]:
        best: Optional[Tuple[Parser, DetectionResult]] = None
        for p in self._parsers:
            try:
                dr = p.detect(url, doc)
            except Exception as e:
                dr = DetectionResult(score=0, reason=f"detect error: {e}")
            if best is None or dr.score > best[1].score:
                best = (p, dr)
        assert best is not None, "No parsers registered"
        return best

