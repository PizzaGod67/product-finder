"""Etsy Open API v3 client -- active listing search only.

Endpoint: GET https://openapi.etsy.com/v3/application/listings/active
(this is the v3 equivalent of the old `findAllListingsActive` method)

Authentication: your app's credentials in the `x-api-key` header, colon-joined:

    x-api-key: <keystring>:<shared_secret>

Both values come from https://www.etsy.com/developers/your-apps. Etsy requires
this API key on *every* request. Only endpoints that touch private user data or
write anything additionally need an OAuth 2.0 token -- and this one does not,
which is why it is the best place for a beginner to start.

Docs: https://developers.etsy.com/documentation/reference/#operation/findAllListingsActive

No scraping anywhere: every number here comes from that endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cache import Cache
from .http import request_json

BASE_URL = "https://openapi.etsy.com/v3/application"
# Etsy caps `limit` at 100 per request, so ~100 listings is one call.
MAX_LIMIT = 100


@dataclass
class EtsyListing:
    """One active Etsy listing, flattened into the fields we care about."""

    listing_id: int
    title: str
    price: float
    currency: str
    num_favorers: int
    shop_name: str
    tags: list[str] = field(default_factory=list)
    url: str = ""
    quantity: int = 0
    views: int = 0

    @classmethod
    def from_api(cls, raw: dict[str, Any], shop_names: dict[int, str]) -> "EtsyListing":
        # v3 returns money as {amount: 1299, divisor: 100, currency_code: "USD"}
        price_obj = raw.get("price") or {}
        amount = price_obj.get("amount")
        divisor = price_obj.get("divisor") or 100
        try:
            price = float(amount) / float(divisor) if amount is not None else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            price = 0.0

        shop_id = raw.get("shop_id")
        # `includes=Shop` nests the shop; otherwise we fall back to a lookup map.
        inline_shop = raw.get("Shop") or raw.get("shop") or {}
        shop_name = (
            inline_shop.get("shop_name")
            or shop_names.get(shop_id, "")
            or (f"shop_{shop_id}" if shop_id else "unknown")
        )

        return cls(
            listing_id=int(raw.get("listing_id") or 0),
            title=(raw.get("title") or "").strip(),
            price=round(price, 2),
            currency=price_obj.get("currency_code") or "USD",
            num_favorers=int(raw.get("num_favorers") or 0),
            shop_name=shop_name,
            tags=[t for t in (raw.get("tags") or []) if isinstance(t, str)],
            url=raw.get("url") or f"https://www.etsy.com/listing/{raw.get('listing_id')}",
            quantity=int(raw.get("quantity") or 0),
            views=int(raw.get("views") or 0),
        )


class EtsyClient:
    def __init__(self, api_key: str, cache: Cache, currency: str = "USD"):
        # `api_key` is the full header value, i.e. "keystring:shared_secret".
        # Build it with Settings.etsy_auth rather than assembling it by hand.
        self.api_key = api_key
        self.cache = cache
        self.currency = currency

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    def search_active_listings(
        self,
        keyword: str,
        limit: int = 100,
        *,
        refresh: bool = False,
        sort_on: str = "score",
    ) -> tuple[list[EtsyListing], int]:
        """Return (listings, total_matching_listings) for a keyword.

        `total_matching_listings` is Etsy's own count of how many active
        listings match -- that is our competition number, and it is usually far
        bigger than the ~100 listings we actually download.
        """
        listings: list[EtsyListing] = []
        total = 0
        remaining = min(limit, 1000)  # be a good citizen
        offset = 0

        while remaining > 0:
            page_size = min(MAX_LIMIT, remaining)
            payload = self._fetch_page(
                keyword, page_size, offset, sort_on, refresh=refresh
            )
            total = int(payload.get("count") or total)
            results = payload.get("results") or []
            if not results:
                break

            shop_names = _shop_names_from_payload(results)
            listings.extend(EtsyListing.from_api(r, shop_names) for r in results)

            offset += len(results)
            remaining -= len(results)
            if len(results) < page_size or offset >= total:
                break

        return listings, max(total, len(listings))

    def _fetch_page(
        self,
        keyword: str,
        limit: int,
        offset: int,
        sort_on: str,
        *,
        refresh: bool,
    ) -> dict[str, Any]:
        params = {
            "keywords": keyword,
            "limit": limit,
            "offset": offset,
            "sort_on": sort_on,
            "sort_order": "desc",
            # Ask Etsy to nest the shop record so we get shop names in one call.
            "includes": "Shop",
        }
        cache_key = {"endpoint": "listings/active", **params}
        if not refresh:
            cached = self.cache.get("etsy", cache_key)
            if cached is not None:
                return cached

        payload = request_json(
            f"{BASE_URL}/listings/active", params=params, headers=self._headers
        )
        if not isinstance(payload, dict):
            payload = {"count": 0, "results": []}
        self.cache.set("etsy", cache_key, payload)
        return payload


def _shop_names_from_payload(results: list[dict[str, Any]]) -> dict[int, str]:
    """Build shop_id -> shop_name from whatever the payload gave us."""
    names: dict[int, str] = {}
    for item in results:
        shop = item.get("Shop") or item.get("shop") or {}
        shop_id = shop.get("shop_id") or item.get("shop_id")
        name = shop.get("shop_name")
        if shop_id and name:
            names[int(shop_id)] = name
    return names
