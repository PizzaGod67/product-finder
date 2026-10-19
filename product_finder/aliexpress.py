"""AliExpress Open Platform / Affiliate API client.

Endpoint: POST https://api-sg.aliexpress.com/sync
Method:   aliexpress.affiliate.product.query

Unlike Etsy, AliExpress does not take a plain API key. Every request must be
*signed*: you build a string out of all your parameters, hash it with your app
secret, and send the result as `sign`. That proves the request came from you
without ever putting the secret on the wire. The algorithm is implemented in
`sign_params` below and is worth reading once -- it is the same scheme used
across Alibaba's "TOP" platform.

Docs: https://openservice.aliexpress.com  (Affiliate -> API reference)

No scraping: every number comes from this signed API.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any

from .cache import Cache
from .http import ApiError, request_json

METHOD_PRODUCT_QUERY = "aliexpress.affiliate.product.query"


def sign_params(params: dict[str, Any], app_secret: str, method: str = "sha256") -> str:
    """Return the `sign` value for an AliExpress Open Platform request.

    The recipe:
      1. Drop `sign` itself and any empty values.
      2. Sort the remaining parameters by key name.
      3. Glue them into one string: key1value1key2value2...
      4. Hash it with your app secret and upper-case the hex digest.

    Two hash flavours exist; `sha256` (HMAC) is the current default, `md5`
    is the legacy one that wraps the string in the secret on both sides.
    """
    items = sorted(
        (k, str(v))
        for k, v in params.items()
        if k != "sign" and v not in (None, "")
    )
    concatenated = "".join(f"{k}{v}" for k, v in items)

    if method == "md5":
        payload = f"{app_secret}{concatenated}{app_secret}".encode("utf-8")
        return hashlib.md5(payload).hexdigest().upper()

    return (
        hmac.new(
            app_secret.encode("utf-8"), concatenated.encode("utf-8"), hashlib.sha256
        )
        .hexdigest()
        .upper()
    )


def _as_float(value: Any) -> float:
    """AliExpress sends prices as strings like '3.47'. Be forgiving."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _as_rating(value: Any) -> float:
    """`evaluate_rate` arrives as '91.3%'. Turn it into 4.57 stars (out of 5)."""
    if value is None:
        return 0.0
    text = str(value).strip()
    if text.endswith("%"):
        percent = _as_float(text[:-1])
        return round(percent / 100.0 * 5.0, 2)
    raw = _as_float(text)
    # Some responses already use a 0-5 scale.
    return round(raw if raw <= 5 else raw / 100.0 * 5.0, 2)


@dataclass
class AliProduct:
    """One AliExpress product, flattened."""

    product_id: str
    title: str
    price: float
    currency: str
    shipping: float
    shipping_is_estimate: bool
    orders: int
    rating: float
    url: str

    @property
    def landed_cost(self) -> float:
        """What the item actually costs you, delivered."""
        return round(self.price + self.shipping, 2)

    @classmethod
    def from_api(cls, raw: dict[str, Any], assumed_shipping: float) -> "AliProduct":
        price = _as_float(
            raw.get("target_sale_price")
            or raw.get("sale_price")
            or raw.get("target_original_price")
            or raw.get("original_price")
        )

        # The affiliate product endpoint usually does NOT include a shipping
        # price (that lives behind the freight/logistics APIs, which need extra
        # permissions). We use a real value when one is present and otherwise
        # fall back to your configured assumption -- flagged in the output so
        # you always know which is which.
        shipping_raw = None
        for key in (
            "target_shipping_price",
            "shipping_price",
            "freight_amount",
            "ship_cost",
        ):
            if raw.get(key) not in (None, ""):
                shipping_raw = raw[key]
                break
        shipping_is_estimate = shipping_raw is None
        shipping = assumed_shipping if shipping_is_estimate else _as_float(shipping_raw)

        return cls(
            product_id=str(raw.get("product_id") or raw.get("productId") or ""),
            title=(raw.get("product_title") or raw.get("subject") or "").strip(),
            price=round(price, 2),
            currency=(
                raw.get("target_sale_price_currency")
                or raw.get("currency_code")
                or "USD"
            ),
            shipping=round(shipping, 2),
            shipping_is_estimate=shipping_is_estimate,
            orders=int(_as_float(raw.get("lastest_volume") or raw.get("volume") or 0)),
            rating=_as_rating(raw.get("evaluate_rate") or raw.get("average_star")),
            # promotion_link is your affiliate link; product_detail_url is plain.
            url=(
                raw.get("promotion_link")
                or raw.get("product_detail_url")
                or (
                    f"https://www.aliexpress.com/item/{raw.get('product_id')}.html"
                    if raw.get("product_id")
                    else ""
                )
            ),
        )


class AliExpressClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        cache: Cache,
        *,
        tracking_id: str = "",
        gateway: str = "https://api-sg.aliexpress.com/sync",
        sign_method: str = "sha256",
        currency: str = "USD",
        ship_to_country: str = "US",
        assumed_shipping: float = 2.50,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.cache = cache
        self.tracking_id = tracking_id
        self.gateway = gateway
        self.sign_method = sign_method
        self.currency = currency
        self.ship_to_country = ship_to_country
        self.assumed_shipping = assumed_shipping

    def search_products(
        self,
        keyword: str,
        limit: int = 40,
        *,
        refresh: bool = False,
        sort: str = "SALE_PRICE_ASC",
    ) -> list[AliProduct]:
        """Search AliExpress for a keyword and return flattened products."""
        page_size = max(1, min(50, limit))
        cache_key = {
            "method": METHOD_PRODUCT_QUERY,
            "keywords": keyword,
            "page_size": page_size,
            "currency": self.currency,
            "ship_to": self.ship_to_country,
            "sort": sort,
        }
        if not refresh:
            cached = self.cache.get("aliexpress", cache_key)
            if cached is not None:
                return [
                    AliProduct.from_api(item, self.assumed_shipping) for item in cached
                ]

        params: dict[str, Any] = {
            # --- platform-wide parameters ---
            "app_key": self.app_key,
            "method": METHOD_PRODUCT_QUERY,
            "sign_method": self.sign_method,
            "timestamp": str(int(time.time() * 1000)),
            "format": "json",
            "v": "2.0",
            # --- parameters for this particular method ---
            "keywords": keyword,
            "page_no": 1,
            "page_size": page_size,
            "target_currency": self.currency,
            "target_language": "EN",
            "ship_to_country": self.ship_to_country,
            "sort": sort,
            "fields": ",".join(
                [
                    "product_id",
                    "product_title",
                    "target_sale_price",
                    "target_sale_price_currency",
                    "original_price",
                    "lastest_volume",
                    "evaluate_rate",
                    "product_detail_url",
                    "promotion_link",
                    "shop_url",
                ]
            ),
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        params["sign"] = sign_params(params, self.app_secret, self.sign_method)

        payload = request_json(self.gateway, method="POST", data=params)
        products = _extract_products(payload)
        self.cache.set("aliexpress", cache_key, products)
        return [AliProduct.from_api(item, self.assumed_shipping) for item in products]


def _extract_products(payload: Any) -> list[dict[str, Any]]:
    """Dig the product list out of AliExpress's deeply nested response.

    A success looks roughly like:

        {"aliexpress_affiliate_product_query_response":
          {"resp_result": {"resp_code": 200,
            "result": {"products": {"product": [ ... ]}}}}}

    but the wrapper keys vary between gateway versions, so we walk the tree
    instead of hard-coding one path. Errors come back as `error_response`.
    """
    if not isinstance(payload, dict):
        return []

    if "error_response" in payload:
        err = payload["error_response"] or {}
        raise ApiError(
            "AliExpress rejected the request: "
            f"{err.get('msg') or err.get('sub_msg') or err}\n"
            f"  code={err.get('code')} sub_code={err.get('sub_code')}\n"
            "  A 'sign' error almost always means ALIEXPRESS_APP_SECRET is wrong,\n"
            "  or your system clock is off. 'IncompleteSignature'/'InvalidAccess'\n"
            "  can also mean your app is not yet approved for the affiliate API."
        )

    # Check the business-level status code, which is separate from HTTP status.
    resp_result = _find_key(payload, "resp_result")
    if isinstance(resp_result, dict):
        code = resp_result.get("resp_code")
        if code is not None and int(_num(code)) not in (200, 0):
            raise ApiError(
                f"AliExpress returned resp_code {code}: "
                f"{resp_result.get('resp_msg') or 'no message'}"
            )

    products = _find_key(payload, "products")
    if isinstance(products, dict):
        products = products.get("product")
    if isinstance(products, dict):
        products = [products]
    if not isinstance(products, list):
        return []
    return [p for p in products if isinstance(p, dict)]


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _find_key(node: Any, target: str) -> Any:
    """Breadth-first search for the first dict value stored under `target`."""
    queue: list[Any] = [node]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            if target in current:
                return current[target]
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return None
