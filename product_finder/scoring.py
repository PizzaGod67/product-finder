"""Scoring demand and competition.

Etsy's public API gives us two useful signals and no sales figures:

  * `num_favorers` -- how many people hearted a listing. A proxy for demand:
    people favourite things they want but have not bought yet.
  * the total count of active listings matching the keyword -- a proxy for
    competition.

The sweet spot you are hunting for is **high favourites, low competition**:
lots of want, few sellers. Everything below is a transparent way of ranking
that, not a crystal ball. Treat the scores as a way to sort a shortlist, then
look at the actual listings yourself.

All scores are 0-100 and use a logarithm, because these numbers are wildly
skewed -- going from 10 to 100 competing listings matters far more than going
from 9,010 to 9,100.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .economics import price_spread, typical_etsy_price
from .etsy import EtsyListing

# Reference points for the log scales. A keyword averaging ~150 favourites per
# listing scores ~100 on demand; one with ~20,000 active listings scores ~0 on
# competition. Tuned for craft-supply niches; change them if your category
# behaves differently.
DEMAND_REFERENCE = 150.0
COMPETITION_REFERENCE = 20000.0

# Thresholds for the "low competition / high favourites" flag.
LOW_COMPETITION_LISTINGS = 2500
HIGH_FAVORITES_AVERAGE = 25.0


def _log_scale(value: float, reference: float) -> float:
    """Map 0..reference onto 0..100 on a log curve, clamped at both ends."""
    value = max(0.0, value)
    if reference <= 1:
        return 0.0
    score = 100.0 * math.log1p(value) / math.log1p(reference)
    return round(max(0.0, min(100.0, score)), 1)


@dataclass
class DemandReport:
    """What we learned about one keyword on Etsy."""

    keyword: str
    listing_count: int  # Etsy's total count of matching active listings
    sampled: int  # how many we actually downloaded
    total_favorites: int
    median_favorites: float
    mean_favorites: float
    top_favorites: int
    unique_shops: int
    typical_price: float
    price_p25: float
    price_p75: float
    demand_score: float
    competition_score: float
    opportunity_score: float
    flags: list[str] = field(default_factory=list)
    top_tags: list[tuple[str, int]] = field(default_factory=list)

    @property
    def is_opportunity(self) -> bool:
        return "LOW COMPETITION + HIGH FAVORITES" in self.flags


def analyse_keyword(
    keyword: str, listings: list[EtsyListing], listing_count: int
) -> DemandReport:
    """Turn a pile of Etsy listings into one scored report."""
    favorites = [item.num_favorers for item in listings]
    sampled = len(listings)
    total_favorites = sum(favorites)
    median_favorites = round(statistics.median(favorites), 1) if favorites else 0.0
    mean_favorites = round(total_favorites / sampled, 1) if sampled else 0.0
    p25, median_price, p75 = price_spread(listings)

    # Demand: driven by the average favourites per listing, with a nudge from
    # the single best performer (proof that something here can take off).
    demand_score = _log_scale(mean_favorites, DEMAND_REFERENCE)
    top = max(favorites) if favorites else 0
    top_bonus = _log_scale(top, DEMAND_REFERENCE * 20) * 0.25
    demand_score = round(min(100.0, demand_score * 0.8 + top_bonus), 1)

    # Competition: inverted, so FEWER rival listings means a HIGHER score.
    competition_score = round(
        100.0 - _log_scale(listing_count, COMPETITION_REFERENCE), 1
    )

    # Opportunity blends the two. Demand is weighted slightly higher: a niche
    # nobody wants is worthless however empty it is.
    opportunity_score = round(demand_score * 0.55 + competition_score * 0.45, 1)

    flags: list[str] = []
    if listing_count and listing_count < LOW_COMPETITION_LISTINGS:
        flags.append("low competition")
    if mean_favorites >= HIGH_FAVORITES_AVERAGE:
        flags.append("high favorites")
    if (
        listing_count
        and listing_count < LOW_COMPETITION_LISTINGS
        and mean_favorites >= HIGH_FAVORITES_AVERAGE
    ):
        flags.insert(0, "LOW COMPETITION + HIGH FAVORITES")
    if listing_count >= 10000:
        flags.append("saturated")
    if sampled and len({item.shop_name for item in listings}) <= max(3, sampled // 10):
        flags.append("dominated by few shops")
    if median_price and median_price < 8:
        flags.append("low price ceiling")

    return DemandReport(
        keyword=keyword,
        listing_count=listing_count,
        sampled=sampled,
        total_favorites=total_favorites,
        median_favorites=median_favorites,
        mean_favorites=mean_favorites,
        top_favorites=top,
        unique_shops=len({item.shop_name for item in listings}),
        typical_price=typical_etsy_price(listings),
        price_p25=p25,
        price_p75=p75,
        demand_score=demand_score,
        competition_score=competition_score,
        opportunity_score=opportunity_score,
        flags=flags,
        top_tags=top_tags(listings),
    )


def top_tags(listings: list[EtsyListing], limit: int = 12) -> list[tuple[str, int]]:
    """The most common tags across the sample -- free keyword ideas."""
    counts: dict[str, int] = {}
    for item in listings:
        for tag in item.tags:
            key = tag.strip().lower()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def niche_score(report: DemandReport, best_margin: float, best_profit: float) -> float:
    """Rank whole keywords against each other for `compare` mode.

    Blends Etsy opportunity (demand + competition) with how much money the best
    AliExpress match would actually leave you. A niche with no profitable
    supplier scores near zero no matter how popular it is.
    """
    # $20 profit per sale = full marks; 60% margin = full marks.
    profit_component = min(100.0, max(0.0, best_profit / 20.0 * 100.0))
    margin_component = min(100.0, max(0.0, (best_margin / 0.6) * 100.0))
    return round(
        report.opportunity_score * 0.5
        + profit_component * 0.3
        + margin_component * 0.2,
        1,
    )
