"""Saving results: one CSV for spreadsheets, one HTML page for reading.

The CSV has one row per AliExpress candidate with every intermediate number,
so you can re-do the maths in Excel or Google Sheets. The HTML report is a
single self-contained file -- no internet needed to open it, no tracking.
"""

from __future__ import annotations

import csv
import datetime as _dt
import html
from pathlib import Path

from .analysis import KeywordResult
from .config import Settings

CSV_COLUMNS = [
    "keyword",
    "niche_score",
    "opportunity_score",
    "demand_score",
    "competition_score",
    "etsy_listing_count",
    "etsy_sampled",
    "etsy_mean_favorites",
    "etsy_median_favorites",
    "etsy_top_favorites",
    "etsy_unique_shops",
    "etsy_typical_price",
    "etsy_price_p25",
    "etsy_price_p75",
    "flags",
    "aliexpress_title",
    "aliexpress_url",
    "aliexpress_price",
    "aliexpress_shipping",
    "shipping_is_estimate",
    "aliexpress_landed_cost",
    "aliexpress_orders",
    "aliexpress_rating",
    "supplier_score",
    "assumed_sell_price",
    "revenue",
    "transaction_fee",
    "payment_fee",
    "listing_fee",
    "offsite_ads_fee",
    "total_fees",
    "estimated_profit",
    "margin",
    "markup",
]


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _slug(text: str) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in text.lower())
    return "-".join(part for part in safe.split("-") if part)[:60] or "search"


def write_csv(results: list[KeywordResult], path: Path) -> Path:
    """Write every candidate of every keyword to one CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for result in results:
            demand = result.demand
            shared = {
                "keyword": result.keyword,
                "niche_score": result.niche_score,
                "opportunity_score": demand.opportunity_score,
                "demand_score": demand.demand_score,
                "competition_score": demand.competition_score,
                "etsy_listing_count": demand.listing_count,
                "etsy_sampled": demand.sampled,
                "etsy_mean_favorites": demand.mean_favorites,
                "etsy_median_favorites": demand.median_favorites,
                "etsy_top_favorites": demand.top_favorites,
                "etsy_unique_shops": demand.unique_shops,
                "etsy_typical_price": demand.typical_price,
                "etsy_price_p25": demand.price_p25,
                "etsy_price_p75": demand.price_p75,
                "flags": "; ".join(demand.flags),
            }
            if not result.candidates:
                writer.writerow(shared)
                continue
            for candidate in result.candidates:
                product, profit = candidate.product, candidate.profit
                writer.writerow(
                    {
                        **shared,
                        "aliexpress_title": product.title,
                        "aliexpress_url": product.url,
                        "aliexpress_price": product.price,
                        "aliexpress_shipping": product.shipping,
                        "shipping_is_estimate": "yes"
                        if product.shipping_is_estimate
                        else "no",
                        "aliexpress_landed_cost": product.landed_cost,
                        "aliexpress_orders": product.orders,
                        "aliexpress_rating": product.rating,
                        "supplier_score": candidate.supplier_score,
                        "assumed_sell_price": profit.etsy_price,
                        "revenue": profit.revenue,
                        "transaction_fee": profit.transaction_fee,
                        "payment_fee": profit.payment_fee,
                        "listing_fee": profit.listing_fee,
                        "offsite_ads_fee": profit.offsite_ads_fee,
                        "total_fees": profit.total_fees,
                        "estimated_profit": profit.profit,
                        "margin": profit.margin,
                        "markup": profit.markup,
                    }
                )
    return path


# --------------------------------------------------------------------------
# HTML report
# --------------------------------------------------------------------------

_STYLE = """
:root {
  --bg: #fbfaf8; --card: #ffffff; --ink: #1d1b19; --muted: #6b6560;
  --line: #e6e1da; --good: #1d7a4c; --bad: #b03a2e; --warn: #9a6a00;
  --accent: #7a4a2b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17161a; --card: #201e23; --ink: #f2efe9; --muted: #a39d96;
    --line: #35313a; --good: #58c08a; --bad: #e8806f; --warn: #e0b24d;
    --accent: #d8a87c;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 16px 64px; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 1120px; margin: 0 auto; }
h1 { font-size: 1.7rem; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 1.15rem; margin: 36px 0 10px; }
.sub { color: var(--muted); font-size: 0.88rem; margin-bottom: 28px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 18px 20px; margin-bottom: 22px; }
.kw { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; }
.kw h2 { margin: 0; }
.score { font-weight: 700; color: var(--accent); }
.stats { display: flex; flex-wrap: wrap; gap: 18px 28px; margin: 14px 0 4px;
  color: var(--muted); font-size: 0.86rem; }
.stats b { display: block; color: var(--ink); font-size: 1.02rem; font-weight: 650; }
.flags { margin: 10px 0 0; display: flex; flex-wrap: wrap; gap: 6px; }
.flag { font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em;
  padding: 3px 8px; border-radius: 999px; border: 1px solid var(--line);
  color: var(--muted); }
.flag.hit { color: var(--good); border-color: var(--good); font-weight: 650; }
.flag.risk { color: var(--bad); border-color: var(--bad); }
table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 0.87rem; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.profit-good { color: var(--good); font-weight: 650; }
.profit-bad { color: var(--bad); }
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }
a:hover { border-bottom-color: currentColor; }
.note { background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-left: 3px solid var(--warn); padding: 10px 14px; border-radius: 6px;
  font-size: 0.85rem; margin: 12px 0; }
.tags { color: var(--muted); font-size: 0.82rem; margin-top: 12px; }
footer { color: var(--muted); font-size: 0.8rem; margin-top: 44px;
  border-top: 1px solid var(--line); padding-top: 16px; }
@media (max-width: 720px) {
  table { display: block; overflow-x: auto; white-space: nowrap; }
}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _flag_class(flag: str) -> str:
    if flag.isupper():
        return "flag hit"
    if flag in ("saturated", "dominated by few shops", "low price ceiling"):
        return "flag risk"
    return "flag"


def _summary_table(results: list[KeywordResult]) -> str:
    rows = []
    for result in sorted(results, key=lambda r: r.niche_score, reverse=True):
        best = result.best
        rows.append(
            "<tr>"
            f"<td>{_esc(result.keyword)}</td>"
            f'<td class="num"><span class="score">{result.niche_score:.0f}</span></td>'
            f'<td class="num">{result.demand.opportunity_score:.0f}</td>'
            f'<td class="num">{result.demand.listing_count:,}</td>'
            f'<td class="num">{result.demand.mean_favorites:,.1f}</td>'
            f'<td class="num">${result.demand.typical_price:,.2f}</td>'
            f'<td class="num">{("$%.2f" % best.profit.profit) if best else "--"}</td>'
            f'<td class="num">{("%.0f%%" % (best.profit.margin * 100)) if best else "--"}</td>'
            "</tr>"
        )
    return (
        '<table><thead><tr><th>Keyword</th><th class="num">Niche score</th>'
        '<th class="num">Opportunity</th><th class="num">Competing listings</th>'
        '<th class="num">Avg favorites</th><th class="num">Typical price</th>'
        '<th class="num">Best profit</th><th class="num">Margin</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _candidate_table(result: KeywordResult) -> str:
    if not result.candidates:
        return '<p class="note">No profitable AliExpress matches found for this keyword.</p>'
    rows = []
    for candidate in result.candidates:
        product, profit = candidate.product, candidate.profit
        cls = "profit-good" if profit.is_viable else "profit-bad"
        ship = f"${product.shipping:,.2f}"
        if product.shipping_is_estimate:
            ship = f"~{ship}"
        rows.append(
            "<tr>"
            f'<td><a href="{_esc(product.url)}" target="_blank" rel="noopener noreferrer">'
            f"{_esc(product.title[:90])}</a></td>"
            f'<td class="num">${product.price:,.2f}</td>'
            f'<td class="num">{ship}</td>'
            f'<td class="num">${product.landed_cost:,.2f}</td>'
            f'<td class="num">{product.orders:,}</td>'
            f'<td class="num">{product.rating:.1f}</td>'
            f'<td class="num">{candidate.supplier_score:.0f}</td>'
            f'<td class="num">${profit.total_fees:,.2f}</td>'
            f'<td class="num {cls}">${profit.profit:,.2f}</td>'
            f'<td class="num {cls}">{profit.margin * 100:.0f}%</td>'
            "</tr>"
        )
    return (
        '<table><thead><tr><th>AliExpress product</th><th class="num">Cost</th>'
        '<th class="num">Ship</th><th class="num">Landed</th><th class="num">Orders</th>'
        '<th class="num">Rating</th><th class="num">Supplier</th>'
        '<th class="num">Etsy fees</th><th class="num">Profit</th><th class="num">Margin</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _top_listings_table(result: KeywordResult, limit: int = 8) -> str:
    listings = sorted(result.listings, key=lambda l: l.num_favorers, reverse=True)[:limit]
    if not listings:
        return ""
    rows = "".join(
        "<tr>"
        f'<td><a href="{_esc(item.url)}" target="_blank" rel="noopener noreferrer">'
        f"{_esc(item.title[:80])}</a></td>"
        f"<td>{_esc(item.shop_name)}</td>"
        f'<td class="num">${item.price:,.2f}</td>'
        f'<td class="num">{item.num_favorers:,}</td>'
        "</tr>"
        for item in listings
    )
    return (
        "<h3 style='font-size:0.95rem;margin:22px 0 0'>Most-favorited Etsy listings</h3>"
        '<table><thead><tr><th>Listing</th><th>Shop</th><th class="num">Price</th>'
        f'<th class="num">Favorites</th></tr></thead><tbody>{rows}</tbody></table>'
    )


def write_html(
    results: list[KeywordResult], path: Path, settings: Settings, mode: str = "search"
) -> Path:
    """Write a single self-contained HTML report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = _dt.datetime.now().strftime("%d %B %Y at %H:%M")
    fees = settings.fees

    blocks: list[str] = []
    if len(results) > 1:
        blocks.append(
            f'<div class="card"><h2>Niche comparison</h2>{_summary_table(results)}</div>'
        )

    for result in sorted(results, key=lambda r: r.niche_score, reverse=True):
        demand = result.demand
        flags = "".join(
            f'<span class="{_flag_class(f)}">{_esc(f)}</span>' for f in demand.flags
        )
        warnings = "".join(f'<p class="note">{_esc(w)}</p>' for w in result.warnings)
        tags = ", ".join(f"{_esc(t)} ({n})" for t, n in demand.top_tags[:10])
        blocks.append(
            f"""<div class="card">
  <div class="kw"><h2>{_esc(result.keyword)}</h2>
    <span class="score">niche score {result.niche_score:.0f}/100</span></div>
  <div class="stats">
    <div>Competing listings<b>{demand.listing_count:,}</b></div>
    <div>Sampled<b>{demand.sampled}</b></div>
    <div>Avg favorites<b>{demand.mean_favorites:,.1f}</b></div>
    <div>Top listing<b>{demand.top_favorites:,} favs</b></div>
    <div>Unique shops<b>{demand.unique_shops}</b></div>
    <div>Typical price<b>${demand.typical_price:,.2f}</b></div>
    <div>Price range<b>${demand.price_p25:,.2f} - ${demand.price_p75:,.2f}</b></div>
    <div>Demand<b>{demand.demand_score:.0f}/100</b></div>
    <div>Low competition<b>{demand.competition_score:.0f}/100</b></div>
  </div>
  <div class="flags">{flags}</div>
  {warnings}
  {_candidate_table(result)}
  {f'<p class="tags"><strong>Common tags:</strong> {tags}</p>' if tags else ''}
  {_top_listings_table(result)}
</div>"""
        )

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>product-finder report</title>
<style>{_STYLE}</style></head>
<body><div class="wrap">
<h1>product-finder report</h1>
<p class="sub">Generated {generated} &middot; mode: {_esc(mode)} &middot;
 data from the Etsy Open API v3 and the AliExpress Affiliate API</p>
{''.join(blocks)}
<footer>
<p><strong>Fee model used:</strong> {fees.transaction_rate * 100:.2f}% transaction
 + {fees.payment_rate * 100:.2f}% + ${fees.payment_flat:.2f} payment processing
 + ${fees.listing_flat:.2f} listing
 {f'+ {fees.offsite_ads_rate * 100:.0f}% offsite ads' if fees.offsite_ads_rate else ''}.
 Selling price assumed = median price of the sampled Etsy listings.</p>
<p><strong>Read these as estimates, not forecasts.</strong> Favorites are a proxy
 for demand, not sales. Profit excludes taxes, duty, currency conversion, returns,
 advertising and your own time. Rows marked <code>~</code> use an assumed shipping
 cost of ${settings.assumed_shipping:.2f} because the API did not report one.
 Always verify prices, shipping and supplier reliability on the product page,
 and check Etsy's current fee schedule and its policies on reselling before listing.</p>
</footer>
</div></body></html>"""
    path.write_text(document, encoding="utf-8")
    return path


def default_paths(
    keywords: list[str], output_dir: Path, mode: str
) -> tuple[Path, Path]:
    """Pick sensible, non-clashing file names for this run."""
    label = _slug(keywords[0] if len(keywords) == 1 else f"{mode}-{len(keywords)}-keywords")
    stem = f"{label}-{_timestamp()}"
    return output_dir / f"{stem}.csv", output_dir / f"{stem}.html"
