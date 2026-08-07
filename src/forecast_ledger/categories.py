from dataclasses import dataclass
from enum import Enum

from forecast_ledger.discovery import MarketCandidate


class ProtocolCategory(str, Enum):
    TECHNOLOGY = "technology"
    BUSINESS = "business"
    SCIENCE = "science"
    GEOPOLITICS = "geopolitics"


CATEGORY_TAGS: dict[ProtocolCategory, frozenset[str]] = {
    ProtocolCategory.TECHNOLOGY: frozenset(
        {
            "tech",
            "ai",
        }
    ),
    ProtocolCategory.BUSINESS: frozenset(
        {
            "business",
        }
    ),
    ProtocolCategory.SCIENCE: frozenset(
        {
            "science",
        }
    ),
    ProtocolCategory.GEOPOLITICS: frozenset(
        {
            "geopolitics",
        }
    ),
}


@dataclass(frozen=True)
class CategoryMatch:
    candidate: MarketCandidate
    categories: tuple[ProtocolCategory, ...]
    matched_tags: tuple[str, ...]

    @property
    def included(self) -> bool:
        return bool(self.categories)


def classify_candidate(
    candidate: MarketCandidate,
) -> CategoryMatch:
    candidate_tags = set(candidate.tag_slugs)

    categories: list[ProtocolCategory] = []
    matched_tags: set[str] = set()

    for category, allowed_tags in CATEGORY_TAGS.items():
        overlap = candidate_tags & allowed_tags

        if overlap:
            categories.append(category)
            matched_tags.update(overlap)

    return CategoryMatch(
        candidate=candidate,
        categories=tuple(categories),
        matched_tags=tuple(sorted(matched_tags)),
    )


def filter_protocol_categories(
    candidates: tuple[MarketCandidate, ...],
) -> tuple[CategoryMatch, ...]:
    matches = tuple(
        classify_candidate(candidate)
        for candidate in candidates
    )

    return tuple(
        match
        for match in matches
        if match.included
    )
