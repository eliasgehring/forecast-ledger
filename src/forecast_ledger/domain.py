from dataclasses import dataclass
from datetime import datetime
from enum import Enum


def require_timezone_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def require_probability(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must lie between 0 and 1.")


@dataclass(frozen=True)
class Market:
    market_id: str
    question: str
    resolution_rules: str
    close_time: datetime
    yes_token_id: str
    no_token_id: str

    def __post_init__(self) -> None:
        if not self.market_id:
            raise ValueError("market_id must not be empty.")

        if not self.question:
            raise ValueError("question must not be empty.")

        if not self.resolution_rules:
            raise ValueError("resolution_rules must not be empty.")

        if not self.yes_token_id:
            raise ValueError("yes_token_id must not be empty.")

        if not self.no_token_id:
            raise ValueError("no_token_id must not be empty.")

        if self.yes_token_id == self.no_token_id:
            raise ValueError("YES and NO token IDs must be different.")

        require_timezone_aware(self.close_time, "close_time")


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    market_id: str
    observed_at: datetime

    yes_bid: float
    yes_ask: float

    no_bid: float | None = None
    no_ask: float | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id must not be empty.")

        if not self.market_id:
            raise ValueError("market_id must not be empty.")

        require_timezone_aware(self.observed_at, "observed_at")

        require_probability(self.yes_bid, "yes_bid")
        require_probability(self.yes_ask, "yes_ask")

        if self.yes_bid > self.yes_ask:
            raise ValueError("yes_bid must not exceed yes_ask.")

        if (self.no_bid is None) != (self.no_ask is None):
            raise ValueError("no_bid and no_ask must either both exist or both be absent.")

        if self.no_bid is not None and self.no_ask is not None:
            require_probability(self.no_bid, "no_bid")
            require_probability(self.no_ask, "no_ask")

            if self.no_bid > self.no_ask:
                raise ValueError("no_bid must not exceed no_ask.")

    @property
    def market_probability(self) -> float:
        """
        Protocol v0.1 market benchmark.

        Always means the midpoint of the YES book.
        """
        return (self.yes_bid + self.yes_ask) / 2.0

    @property
    def yes_spread(self) -> float:
        return self.yes_ask - self.yes_bid

    @property
    def no_midpoint(self) -> float | None:
        if self.no_bid is None or self.no_ask is None:
            return None

        return (self.no_bid + self.no_ask) / 2.0

    @property
    def no_implied_yes_probability(self) -> float | None:
        midpoint = self.no_midpoint

        if midpoint is None:
            return None

        return 1.0 - midpoint


class TimestampQuality(str, Enum):
    VERIFIED = "verified"
    REPORTED = "reported"
    DATE_ONLY = "date_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_url: str
    source_name: str
    title: str
    published_at: datetime
    retrieved_at: datetime
    excerpt: str
    timestamp_quality: TimestampQuality

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id must not be empty.")

        if not self.source_url:
            raise ValueError("source_url must not be empty.")

        if not self.source_name:
            raise ValueError("source_name must not be empty.")

        if not self.title:
            raise ValueError("title must not be empty.")

        if not self.excerpt:
            raise ValueError("excerpt must not be empty.")

        require_timezone_aware(self.published_at, "published_at")
        require_timezone_aware(self.retrieved_at, "retrieved_at")


@dataclass(frozen=True)
class EvidencePacket:
    packet_id: str
    market_id: str
    snapshot_id: str
    information_cutoff: datetime
    evidence_ids: tuple[str, ...]
    retrieval_model: str
    retrieval_prompt_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.packet_id:
            raise ValueError("packet_id must not be empty.")

        if not self.market_id:
            raise ValueError("market_id must not be empty.")

        if not self.snapshot_id:
            raise ValueError("snapshot_id must not be empty.")

        if not self.retrieval_model:
            raise ValueError("retrieval_model must not be empty.")

        if not self.retrieval_prompt_version:
            raise ValueError("retrieval_prompt_version must not be empty.")

        require_timezone_aware(self.information_cutoff, "information_cutoff")
        require_timezone_aware(self.created_at, "created_at")

        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must not contain duplicates.")

        if any(not evidence_id for evidence_id in self.evidence_ids):
            raise ValueError("evidence_ids must not contain empty values.")

