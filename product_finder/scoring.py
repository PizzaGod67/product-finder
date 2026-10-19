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

from .config import Thresholds
from .economics import price_spread, typical_etsy_price
from .etsy import EtsyListing

def _log_range(value: float, low: float, high: float, invert: bool = False) -> float:
    """Map the range low..high onto 0..100 on a log curve.

    At or below `low` you get 0; at or above `high` you get 100; in between the
    curve is logarithmic, because these numbers are wildly skewed -- the step
    from 10 to 100 competing listings matters far more than 9,010 to 9,100.

    With `invert=True` the scale runs the other way, so a SMALL value scores
    high. That is what we want for competition: fewer rivals is better.

    Mapping a *range* rather than counting up from zero matters. An earlier
    version scaled from 0 to a single reference point, and the result was that
    every real Etsy keyword scored 100 on demand, which made comparing niches
    meaningless.
    """
    low = max(1.0, low)
    high = max(low + 1.0, high)
    value = max(1.0, value)

    span = math.log(high) - math.log(low)
    position = (math.log(value) - math.log(low)) / span
    if invert:
        position = 1.0 - position
    return round(max(0.0, min(100.0, position * 100.0)), 1)


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
    keyword: str,
    listings: list[EtsyListing],
    listing_count: int,
    thresholds: Thresholds | None = None,
) -> DemandReport:
    """Turn a pile of Etsy listings into one scored report."""
    limits = thresholds or Thresholds()
    favorites = [item.num_favorers for item in listings]
    sampled = len(listings)
    total_favorites = sum(favorites)
    median_favorites = round(statistics.median(favorites), 1) if favorites else 0.0
    mean_favorites = round(total_favorites / sampled, 1) if sampled else 0.0
    p25, median_price, p75 = price_spread(listings)

    # Demand: mostly the average favourites per listing, with a nudge from the
    # single best performer (proof that something here can take off).
    top = max(favorites) if favorites else 0
    average_component = _log_range(
        mean_favorites, limits.demand_favorites_low, limits.demand_favorites_high
    )
    top_component = _log_range(
        top,
        limits.demand_favorites_low * 10,
        limits.demand_favorites_high * 20,
    )
    demand_score = round(
        min(100.0, average_component * 0.8 + top_component * 0.2), 1
    )

    # Competition: inverted, so FEWER rival listings means a HIGHER score.
    competition_score = _log_range(
        listing_count,
        limits.competition_listings_low,
        limits.competition_listings_high,
        invert=True,
    )

    # Opportunity blends the two. Demand is weighted slightly higher: a niche
    # nobody wants is worthless however empty it is.
    opportunity_score = round(demand_score * 0.55 + competition_score * 0.45, 1)

    flags: list[str] = []
    low_competition = bool(listing_count) and listing_count < limits.low_competition_listings
    high_favorites = mean_favorites >= limits.high_favorites_average
    if low_competition:
        flags.append("low competition")
    if high_favorites:
        flags.append("high favorites")
    if low_competition and high_favorites:
        flags.insert(0, "LOW COMPETITION + HIGH FAVORITES")
    if listing_count >= limits.saturated_listings:
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
