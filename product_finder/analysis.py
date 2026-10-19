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
from .scoring import DemandReport, analyse_keyword, niche_score


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
    demand = analyse_keyword(keyword, listings, listing_count)
    result = KeywordResult(keyword=keyword, demand=demand, listings=listings)

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
