"""The profit maths.

Everything here is plain arithmetic, deliberately kept in one small file so
you can check it against your own spreadsheet.

The model, for one sale:

    revenue  = what the buyer pays you (item price + any shipping you charge)
    fees     = Etsy's cut (percentages of revenue + flat amounts)
    cost     = what you pay AliExpress (item price + shipping to you)
    profit   = revenue - fees - cost
    margin   = profit / revenue

What is NOT modelled (so your real profit will be a bit lower):
  - sales tax / VAT, import duty, and currency conversion spreads
  - Etsy Ads or Offsite Ads, unless you set ETSY_OFFSITE_ADS_RATE
  - returns, breakage, and lost parcels
  - your own time, packaging, and any value you add to the product
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .aliexpress import AliProduct
from .config import Fees
from .etsy import EtsyListing


@dataclass
class ProfitBreakdown:
    """Every intermediate number, so nothing is a black box."""

    etsy_price: float
    revenue: float
    aliexpress_price: float
    shipping_cost: float
    shipping_is_estimate: bool
    total_cost: float
    transaction_fee: float
    payment_fee: float
    listing_fee: float
    offsite_ads_fee: float
    total_fees: float
    profit: float
    margin: float
    markup: float

    @property
    def is_viable(self) -> bool:
        """A rough sanity bar: makes real money, not pennies."""
        return self.profit >= 3.0 and self.margin >= 0.20


def estimate_profit(
    etsy_price: float, product: AliProduct, fees: Fees
) -> ProfitBreakdown:
    """Work out the per-sale profit of reselling `product` at `etsy_price`."""
    etsy_price = max(0.0, float(etsy_price))
    revenue = etsy_price + fees.shipping_charged

    transaction_fee = revenue * fees.transaction_rate
    payment_fee = revenue * fees.payment_rate + fees.payment_flat
    listing_fee = fees.listing_flat
    offsite_ads_fee = revenue * fees.offsite_ads_rate
    total_fees = transaction_fee + payment_fee + listing_fee + offsite_ads_fee

    total_cost = product.landed_cost
    profit = revenue - total_fees - total_cost

    return ProfitBreakdown(
        etsy_price=round(etsy_price, 2),
        revenue=round(revenue, 2),
        aliexpress_price=product.price,
        shipping_cost=product.shipping,
        shipping_is_estimate=product.shipping_is_estimate,
        total_cost=round(total_cost, 2),
        transaction_fee=round(transaction_fee, 2),
        payment_fee=round(payment_fee, 2),
        listing_fee=round(listing_fee, 2),
        offsite_ads_fee=round(offsite_ads_fee, 2),
        total_fees=round(total_fees, 2),
        profit=round(profit, 2),
        margin=round(profit / revenue, 4) if revenue > 0 else 0.0,
        markup=round(revenue / total_cost, 2) if total_cost > 0 else 0.0,
    )


def typical_etsy_price(listings: list[EtsyListing]) -> float:
    """The price to assume you could sell at.

    We use the *median* rather than the average: a handful of $200 "deluxe
    bundle" listings would drag an average far above what you could realistically
    charge, while the median tracks the middle of the market.
    """
    prices = [item.price for item in listings if item.price > 0]
    if not prices:
        return 0.0
    return round(statistics.median(prices), 2)


def price_spread(listings: list[EtsyListing]) -> tuple[float, float, float]:
    """(25th percentile, median, 75th percentile) of Etsy prices."""
    prices = sorted(item.price for item in listings if item.price > 0)
    if not prices:
        return (0.0, 0.0, 0.0)
    if len(prices) < 4:
        median = statistics.median(prices)
        return (round(prices[0], 2), round(median, 2), round(prices[-1], 2))

    def percentile(fraction: float) -> float:
        index = min(len(prices) - 1, max(0, int(round(fraction * (len(prices) - 1)))))
        return round(prices[index], 2)

    return (percentile(0.25), percentile(0.50), percentile(0.75))
