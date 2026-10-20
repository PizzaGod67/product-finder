"""Sample data so you can try the tool before your API keys arrive.

Important: the numbers here are INVENTED. They are shaped exactly like real
API responses, and they are fed through the very same parsing, scoring and
profit code that live data goes through -- so `demo` is both a preview and a
self-test of the maths. But do not make business decisions from them.
"""

from __future__ import annotations

import random

from .aliexpress import AliProduct
from .analysis import KeywordResult, research_keyword
from .config import Settings
from .etsy import EtsyListing

# keyword -> (competing listings, favourite level, price band, supplier cost band)
DEMO_NICHES: dict[str, tuple[int, int, tuple[float, float], tuple[float, float]]] = {
    "wax seal kit": (1_840, 46, (18.0, 42.0), (3.10, 9.40)),
    "resin mold": (24_500, 11, (7.5, 21.0), (1.80, 6.20)),
    "leather stamp set": (2_050, 31, (24.0, 58.0), (6.40, 15.00)),
}

DEMO_TAGS = [
    "craft supplies", "gift for her", "diy kit", "wedding", "journaling",
    "scrapbooking", "handmade tools", "stationery", "beginner kit", "bullet journal",
]


def _fake_etsy_payload(keyword: str, seed: int) -> list[dict]:
    """Build Etsy-v3-shaped listing dicts (money as amount/divisor, etc.)."""
    rng = random.Random(seed)
    _, favorite_level, (low, high), _ = DEMO_NICHES[keyword]
    shops = [f"{keyword.split()[0].title()}Studio{n}" for n in range(1, 13)]
    results = []
    for index in range(60):
        price = round(rng.uniform(low, high), 2)
        favourites = max(0, int(rng.gauss(favorite_level, favorite_level * 0.8)))
        shop = rng.choice(shops)
        results.append(
            {
                "listing_id": 1_000_000 + seed * 1000 + index,
                "title": f"{keyword.title()} - {rng.choice(['Vintage', 'Deluxe', 'Starter', 'Gift', 'Pro'])} "
                f"Set {rng.randint(2, 48)} Pieces",
                "price": {
                    "amount": int(price * 100),
                    "divisor": 100,
                    "currency_code": "USD",
                },
                "num_favorers": favourites,
                "quantity": rng.randint(1, 400),
                "tags": rng.sample(DEMO_TAGS, k=rng.randint(4, 8)),
                "url": f"https://www.etsy.com/listing/{1_000_000 + seed * 1000 + index}",
                "taxonomy_id": rng.choice([1, 1, 1, 1, 1, 1, 2, 3]),
                "shop_id": 500 + shops.index(shop),
                "Shop": {"shop_id": 500 + shops.index(shop), "shop_name": shop},
            }
        )
    return results


def _fake_ali_payload(keyword: str, seed: int) -> list[dict]:
    """Build AliExpress-shaped product dicts (prices as strings, rate as '%')."""
    rng = random.Random(seed + 77)
    _, _, _, (low, high) = DEMO_NICHES[keyword]
    products = []
    for index in range(24):
        price = round(rng.uniform(low, high), 2)
        products.append(
            {
                "product_id": f"3256{seed}{index:04d}",
                "product_title": f"{rng.randint(10, 60)}pcs {keyword.title()} "
                f"{rng.choice(['Brass', 'Wooden Handle', 'Retro', 'DIY', 'Craft'])} "
                "for Scrapbooking Wedding Invitation",
                "target_sale_price": f"{price:.2f}",
                "target_sale_price_currency": "USD",
                "original_price": f"{price * rng.uniform(1.3, 2.2):.2f}",
                "lastest_volume": rng.choice([5, 48, 120, 460, 1_200, 3_400, 9_800]),
                "evaluate_rate": f"{rng.uniform(88.0, 98.5):.1f}%",
                "product_detail_url": f"https://www.aliexpress.com/item/3256{seed}{index:04d}.html",
            }
        )
        # A few listings do report shipping; include some so you can see the
        # difference between a real figure and an assumed one (marked with ~).
        if index % 5 == 0:
            products[-1]["target_shipping_price"] = f"{rng.uniform(0.0, 4.5):.2f}"
    return products


class _DemoEtsyClient:
    """Stands in for EtsyClient, using the real parser on fake payloads."""

    def __init__(self, seed_base: int = 1):
        self.seed_base = seed_base

    def taxonomy_names(self, *, refresh=False):
        return {1: "Craft Supplies & Tools > Stamping",
                2: "Paper & Party Supplies > Stickers",
                3: "Home & Living > Wall Decor"}

    def search_active_listings(self, keyword, limit=100, *, refresh=False, sort_on="score"):
        seed = self.seed_base + abs(hash(keyword)) % 997
        raw = _fake_etsy_payload(keyword, seed)[:limit]
        shop_names = {
            item["Shop"]["shop_id"]: item["Shop"]["shop_name"] for item in raw
        }
        listings = [EtsyListing.from_api(item, shop_names) for item in raw]
        competing = DEMO_NICHES[keyword][0]
        return listings, competing


class _DemoAliClient:
    """Stands in for AliExpressClient, using the real parser on fake payloads."""

    def __init__(self, assumed_shipping: float, seed_base: int = 1):
        self.assumed_shipping = assumed_shipping
        self.seed_base = seed_base

    def search_products(self, keyword, limit=40, *, refresh=False, sort="SALE_PRICE_ASC"):
        seed = self.seed_base + abs(hash(keyword)) % 997
        raw = _fake_ali_payload(keyword, seed)[:limit]
        return [AliProduct.from_api(item, self.assumed_shipping) for item in raw]


def run_demo(
    settings: Settings,
    min_profit: float = 0.0,
    max_candidates: int = 15,
    etsy_only: bool = False,
) -> list[KeywordResult]:
    """Run the full pipeline over the sample niches."""
    etsy = _DemoEtsyClient()
    ali = None if etsy_only else _DemoAliClient(settings.assumed_shipping)
    results = []
    for keyword in DEMO_NICHES:
        results.append(
            research_keyword(
                keyword,
                settings,
                etsy,  # type: ignore[arg-type]
                ali,  # type: ignore[arg-type]
                min_profit=min_profit,
                max_candidates=max_candidates,
            )
        )
    return results
