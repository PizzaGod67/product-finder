"""Putting it all together: one keyword in, one ranked result out.

This is the module the command line calls. It orchestrates:

    Etsy listings  ->  demand/competition report  ->  typical selling price
                                                              |
    AliExpress products  ------------------------------------>  profit per item
                                                              |
                                                    ranked candidate list
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .aliexpress import AliExpressClient, AliProduct
from .config import Settings
from .economics import ProfitBreakdown, estimate_profit
from .etsy import EtsyClient, EtsyListing
from .http import ApiError
from .scoring import DemandReport, analyse_keyword, niche_score, top_tags


@dataclass
class Candidate:
    """One AliExpress product, priced against the Etsy market."""

    product: AliProduct
    profit: ProfitBreakdown
    supplier_score: float

    @property
    def sort_key(self) -> tuple[float, float, float]:
        # Rank by profit first, then by how trustworthy the supplier looks.
        return (self.profit.profit, self.supplier_score, self.profit.margin)


@dataclass
class KeywordResult:
    keyword: str
    demand: DemandReport
    listings: list[EtsyListing]
    candidates: list[Candidate] = field(default_factory=list)
    niche_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    # False when AliExpress was never consulted, so the niche score reflects
    # Etsy demand alone and should be labelled as such rather than compared
    # against keywords that do include sourcing data.
    sourcing_checked: bool = False

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def supplier_confidence(product: AliProduct) -> float:
    """0-100: how much the order count and rating suggest a safe supplier.

    Orders matter more than rating, because almost every AliExpress listing
    shows 4.5+ stars, while order volume is much harder to fake.
    """
    orders = min(100.0, (product.orders / 2000.0) * 100.0)
    rating = (product.rating / 5.0) * 100.0 if product.rating else 50.0
    return round(orders * 0.65 + rating * 0.35, 1)


def discover_keywords(
    seed: str,
    settings: Settings,
    etsy: EtsyClient,
    *,
    limit: int = 12,
    refresh: bool = False,
) -> list[tuple[str, int]]:
    """Suggest related keywords to research, from one seed keyword.

    Etsy sellers tag their own listings, so the tags on the top results for
    "linen dress" are the exact phrases real sellers in that market use. That
    makes them far better research candidates than anything you would invent,
    and it costs one API call.

    Returns (keyword, how many of the sampled listings used it), best first,
    with the seed itself and near-duplicates of it removed.
    """
    listings, _ = etsy.search_active_listings(
        seed, limit=settings.etsy_limit, refresh=refresh
    )
    seed_normalised = " ".join(seed.lower().split())

    suggestions: list[tuple[str, int]] = []
    for tag, count in top_tags(listings, limit=limit * 3):
        if tag == seed_normalised:
            continue
        # Skip tags that are just the seed with a word bolted on; they return
        # nearly the same listings and waste an API call.
        if tag in seed_normalised or seed_normalised in tag:
            continue
        # A tag only one listing used is noise, not a market.
        if count < 2:
            continue
        suggestions.append((tag, count))
        if len(suggestions) >= limit:
            break
    return suggestions


def research_keyword(
    keyword: str,
    settings: Settings,
    etsy: EtsyClient,
    ali: AliExpressClient | None,
    *,
    refresh: bool = False,
    min_profit: float = 0.0,
    max_candidates: int = 15,
) -> KeywordResult:
    """Research a single keyword end to end."""
    listings, listing_count = etsy.search_active_listings(
        keyword, limit=settings.etsy_limit, refresh=refresh
    )
    # The category tree is a nicety: if that call fails we still want the
    # search itself to succeed, just without the category breakdown.
    try:
        taxonomy = etsy.taxonomy_names()
    except ApiError:
        taxonomy = None

    demand = analyse_keyword(
        keyword, listings, listing_count, settings.thresholds, taxonomy
    )
    result = KeywordResult(keyword=keyword, demand=demand, listings=listings)
    # Start from the Etsy-only view. If sourcing data arrives below, this gets
    # recalculated; if it does not, this remains the honest answer rather than
    # the 0 an un-set score would leave behind.
    result.niche_score = demand.opportunity_score

    if not listings:
        result.warnings.append(
            f"Etsy returned no active listings for {keyword!r}. "
            "Try a broader or differently spelled keyword."
        )

    if ali is None:
        result.warnings.append(
            "AliExpress was skipped (either --etsy-only was used, or its keys "
            "are not in your .env), so no sourcing or profit figures were "
            "calculated. The Etsy demand analysis above is still valid."
        )
        return result

    result.sourcing_checked = True
    try:
        products = ali.search_products(
            keyword, limit=settings.aliexpress_limit, refresh=refresh
        )
    except ApiError as exc:
        result.warnings.append(f"AliExpress lookup failed: {exc}")
        return result

    if not products:
        result.warnings.append(
            f"AliExpress returned no products for {keyword!r}."
        )
        return result

    selling_price = demand.typical_price
    if selling_price <= 0:
        result.warnings.append(
            "No usable Etsy prices, so profit could not be estimated."
        )
        return result

    candidates: list[Candidate] = []
    for product in products:
        if product.price <= 0:
            continue
        breakdown = estimate_profit(selling_price, product, settings.fees)
        if breakdown.profit < min_profit:
            continue
        candidates.append(
            Candidate(
                product=product,
                profit=breakdown,
                supplier_score=supplier_confidence(product),
            )
        )

    candidates.sort(key=lambda c: c.sort_key, reverse=True)
    result.candidates = candidates[:max_candidates]

    if not candidates:
        result.warnings.append(
            f"No AliExpress product cleared the minimum profit of "
            f"${min_profit:.2f} at an Etsy price of ${selling_price:.2f}."
        )

    if any(c.product.shipping_is_estimate for c in result.candidates):
        result.warnings.append(
            f"AliExpress did not report shipping costs, so ${settings.assumed_shipping:.2f} "
            "per item was assumed (rows marked with ~). Confirm real shipping "
            "on the product page before committing."
        )

    best = result.best
    result.niche_score = niche_score(
        demand,
        best.profit.margin if best else 0.0,
        best.profit.profit if best else 0.0,
    )
    return result
