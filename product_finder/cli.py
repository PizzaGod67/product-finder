"""The command line: `search`, `compare`, `check`, `cache` and `demo`.

Run `python pf.py --help` to see everything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .aliexpress import AliExpressClient
from .analysis import KeywordResult, research_keyword
from .cache import Cache
from .config import Settings, SettingsError
from .economics import max_sourcing_cost
from .matching import describe_match
from .etsy import EtsyClient
from .http import ApiError
from .report import default_paths, write_csv, write_html
from .table import Painter, money, percent, render_table


# --------------------------------------------------------------------------
# Printing results to the terminal
# --------------------------------------------------------------------------


def print_keyword_result(
    result: KeywordResult, settings: Settings, paint: Painter
) -> None:
    demand = result.demand
    label = "niche score" if result.sourcing_checked else "Etsy-only score"
    print()
    print(paint.bold(f'=== "{result.keyword}" ') + paint.accent(
        f"{label} {result.niche_score:.0f}/100"
    ))

    summary = render_table(
        ["Competing", "Sampled", "Avg favs", "Top favs", "Shops", "Typical price",
         "Price range", "Demand", "Low-comp"],
        [[
            f"{demand.listing_count:,}",
            f"{demand.sampled}",
            f"{demand.mean_favorites:,.1f}",
            f"{demand.top_favorites:,}",
            f"{demand.unique_shops}",
            money(demand.typical_price),
            f"{money(demand.price_p25)}-{money(demand.price_p75)}",
            f"{demand.demand_score:.0f}",
            f"{demand.competition_score:.0f}",
        ]],
        align="rrrrrrrrr",
    )
    print(summary)

    if demand.flags:
        rendered = []
        for flag in demand.flags:
            if flag.isupper():
                rendered.append(paint.good(f"[{flag}]"))
            elif flag in (
                "saturated",
                "dominated by few shops",
                "low price ceiling",
                "mixed categories",
            ):
                rendered.append(paint.bad(f"[{flag}]"))
            else:
                rendered.append(paint.warn(f"[{flag}]"))
        print("Flags: " + " ".join(rendered))

    if demand.category_mix:
        parts = [f"{label} {share:.0f}%" for label, share in demand.category_mix[:4]]
        print(paint.dim("What these listings actually are: ") + ", ".join(parts))
        if "mixed categories" in demand.flags:
            print(paint.bad(
                f"  Careful: only {demand.main_category_share:.0f}% of this keyword's "
                f"listings are {demand.main_category}.\n"
                "  The scores above describe that whole mixture, not one product type."
            ))

    for warning in result.warnings:
        print(paint.warn("Note: ") + warning)

    # Without supplier prices, the actionable number is not profit but the
    # budget: how cheaply you would have to source to make this work at all.
    if not result.candidates and demand.typical_price > 0:
        breakeven = max_sourcing_cost(demand.typical_price, settings.fees)
        healthy = max_sourcing_cost(demand.typical_price, settings.fees, 0.20)
        print()
        print(paint.dim(
            f"  Selling at the {money(demand.typical_price)} median, your landed cost "
            f"(item + shipping) must stay under:"
        ))
        verdict = paint.good if healthy >= 4.0 else paint.bad
        print(
            f"    {money(breakeven)} to break even    "
            f"{verdict(money(healthy))} for a 20% margin"
        )
        if healthy < 4.0:
            print(paint.bad(
                "    That is a very tight budget once AliExpress shipping is "
                "counted. Low-priced\n"
                "    niches look attractive on demand and rarely survive the fees."
            ))

    if result.candidates:
        print()
        print(paint.dim(
            f"Assuming you sell at the Etsy median of {money(demand.typical_price)}:"
        ))
        rows = []
        for index, candidate in enumerate(result.candidates, start=1):
            product, profit = candidate.product, candidate.profit
            ship = money(product.shipping)
            if product.shipping_is_estimate:
                ship = "~" + ship
            profit_text = money(profit.profit)
            profit_text = (
                paint.good(profit_text) if profit.is_viable else paint.bad(profit_text)
            )
            rows.append([
                str(index),
                product.title,
                f"{candidate.match_score:.0f}",
                money(product.price),
                ship,
                money(product.landed_cost),
                f"{product.orders:,}",
                f"{product.rating:.1f}",
                f"{candidate.supplier_score:.0f}",
                money(profit.total_fees),
                profit_text,
                percent(profit.margin),
            ])
        print(render_table(
            ["#", "AliExpress product", "Match", "Cost", "Ship", "Landed",
             "Orders", "Rate", "Supp", "Fees", "Profit", "Margin"],
            rows,
            max_widths=[3, 42, 6, 9, 9, 9, 8, 5, 5, 8, 12, 7],
            align="rlrrrrrrrrrr",
        ))
        best = result.best
        if best:
            print()
            quality = describe_match(best.match_score)
            tint = paint.good if best.match_score >= 35 else paint.bad
            print(
                paint.dim("  Best match ")
                + tint(f"({quality}, {best.match_score:.0f}/100): ")
                + best.product.url
            )
            print(paint.dim(
                "  Match = how much the product title resembles what this Etsy\n"
                "  market sells. Always open the page and check what is in the box."
            ))

    if demand.top_tags:
        tags = ", ".join(f"{tag} ({count})" for tag, count in demand.top_tags[:8])
        print()
        print(paint.dim(f"  Common Etsy tags: {tags}"))


def print_comparison(
    results: list[KeywordResult], settings: Settings, paint: Painter
) -> None:
    ranked = sorted(results, key=lambda r: r.niche_score, reverse=True)
    print()
    print(paint.bold("=== Niche comparison (best first) ==="))
    rows = []
    for position, result in enumerate(ranked, start=1):
        best = result.best
        flag = ""
        if result.demand.is_opportunity:
            flag = paint.good("<- sweet spot")
        elif "saturated" in result.demand.flags:
            flag = paint.bad("saturated")
        rows.append([
            str(position),
            result.keyword,
            f"{result.niche_score:.0f}",
            f"{result.demand.opportunity_score:.0f}",
            f"{result.demand.listing_count:,}",
            f"{result.demand.mean_favorites:,.1f}",
            money(result.demand.typical_price),
            # With no supplier data, show the sourcing budget instead of a
            # profit we cannot know. A tight budget is the real constraint in
            # cheap niches, and it would otherwise be invisible here.
            money(best.profit.profit) if best else (
                money(max_sourcing_cost(
                    result.demand.typical_price, settings.fees, 0.20
                )) if result.demand.typical_price > 0 else "--"
            ),
            percent(best.profit.margin) if best else "--",
            flag,
        ])
    any_profit = any(r.candidates for r in ranked)
    money_column = "Best profit" if any_profit else "Budget @20%"
    print(render_table(
        ["#", "Keyword", "Niche", "Opp", "Competing", "Avg favs",
         "Typical", money_column, "Margin", "Flag"],
        rows,
        max_widths=[3, 30, 6, 5, 11, 9, 10, 12, 7, 16],
        align="rlrrrrrrrl",
    ))
    if not any_profit:
        print(paint.dim(
            "  Budget @20% = the most you can pay a supplier (item + shipping)\n"
            "  and still keep a 20% margin at that typical selling price."
        ))


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def build_clients(
    settings: Settings, args: argparse.Namespace
) -> tuple[EtsyClient, AliExpressClient | None, Cache]:
    cache = Cache(
        settings.cache_dir,
        ttl_hours=args.cache_ttl if args.cache_ttl is not None else settings.cache_ttl_hours,
        enabled=not args.no_cache,
    )
    settings.require_etsy()
    etsy = EtsyClient(settings.etsy_auth, cache, currency=settings.currency)

    ali: AliExpressClient | None = None
    if args.etsy_only:
        pass
    elif settings.aliexpress_app_key and settings.aliexpress_app_secret:
        ali = AliExpressClient(
            settings.aliexpress_app_key,
            settings.aliexpress_app_secret,
            cache,
            tracking_id=settings.aliexpress_tracking_id,
            gateway=settings.aliexpress_gateway,
            sign_method=settings.aliexpress_sign_method,
            currency=settings.currency,
            ship_to_country=settings.ship_to_country,
            assumed_shipping=settings.assumed_shipping,
        )
    return etsy, ali, cache


def run_research(
    keywords: list[str], settings: Settings, args: argparse.Namespace, paint: Painter
) -> list[KeywordResult]:
    etsy, ali, cache = build_clients(settings, args)
    results: list[KeywordResult] = []

    for position, keyword in enumerate(keywords, start=1):
        print(
            paint.dim(f"[{position}/{len(keywords)}] researching {keyword!r} ..."),
            flush=True,
        )
        try:
            results.append(
                research_keyword(
                    keyword,
                    settings,
                    etsy,
                    ali,
                    refresh=args.refresh,
                    min_profit=args.min_profit,
                    max_candidates=args.top,
                    min_match=args.min_match,
                )
            )
        except ApiError as exc:
            print(paint.bad(f"  failed: {exc}"), file=sys.stderr)

    if cache.enabled and (cache.hits or cache.misses):
        print(paint.dim(
            f"  cache: {cache.hits} reused, {cache.misses} fetched fresh"
        ))
    return results


def save_outputs(
    results: list[KeywordResult],
    keywords: list[str],
    settings: Settings,
    args: argparse.Namespace,
    mode: str,
    paint: Painter,
) -> None:
    if args.no_save or not results:
        return
    csv_path, html_path = default_paths(keywords, settings.output_dir, mode)
    if args.csv:
        csv_path = Path(args.csv)
    if args.html:
        html_path = Path(args.html)
    write_csv(results, csv_path)
    write_html(results, html_path, settings, mode=mode)
    print()
    print(paint.bold("Saved:"))
    print(f"  CSV  {csv_path}")
    print(f"  HTML {html_path}")
    print(paint.dim("  (open the HTML file in your browser)"))


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    keyword = " ".join(args.keyword).strip()
    if not keyword:
        print("Please give me a keyword, e.g. pf.py search \"wax seal kit\"")
        return 2
    results = run_research([keyword], settings, args, paint)
    for result in results:
        print_keyword_result(result, settings, paint)
    save_outputs(results, [keyword], settings, args, "search", paint)
    print_disclaimer(paint)
    return 0 if results else 1


def cmd_compare(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    keywords = [k.strip() for k in args.keywords if k.strip()]
    if len(keywords) < 2:
        print("Give me at least two keywords to compare.")
        return 2
    results = run_research(keywords, settings, args, paint)
    if not results:
        return 1
    if not args.brief:
        for result in results:
            print_keyword_result(result, settings, paint)
    print_comparison(results, settings, paint)
    save_outputs(results, keywords, settings, args, "compare", paint)
    print_disclaimer(paint)
    return 0


def cmd_check(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    """Tell the user exactly what is and is not configured."""
    print(paint.bold("product-finder setup check"))
    print()
    joined = ":" in settings.etsy_api_key
    rows = [
        ["Etsy keystring", "set" if settings.etsy_api_key else "MISSING",
         "required for everything"],
        ["Etsy shared secret",
         "set" if (settings.etsy_shared_secret or joined) else "MISSING",
         "required -- sent as keystring:shared_secret"],
        ["AliExpress app key", "set" if settings.aliexpress_app_key else "missing",
         "required for sourcing + profit"],
        ["AliExpress app secret",
         "set" if settings.aliexpress_app_secret else "missing",
         "required for sourcing + profit"],
        ["AliExpress tracking ID",
         "set" if settings.aliexpress_tracking_id else "not set",
         "optional (affiliate links)"],
    ]
    print(render_table(["Setting", "Status", "Notes"], rows))
    print()
    print(paint.bold("Fee model"))
    fees = settings.fees
    print(render_table(
        ["Fee", "Value"],
        [
            ["Transaction", percent(fees.transaction_rate, 2)],
            ["Payment processing",
             f"{percent(fees.payment_rate, 2)} + {money(fees.payment_flat)}"],
            ["Listing", money(fees.listing_flat)],
            ["Offsite ads", percent(fees.offsite_ads_rate, 2)],
            ["Shipping you charge buyers", money(fees.shipping_charged)],
            ["Assumed AliExpress shipping", money(settings.assumed_shipping)],
        ],
    ))
    print()
    print(f"Cache:   {settings.cache_dir}  (TTL {settings.cache_ttl_hours:g}h)")
    print(f"Reports: {settings.output_dir}")

    if not settings.etsy_api_key:
        print()
        print(paint.warn("Next step: ") + "copy .env.example to .env and add your keys.")
        return 1

    if not (settings.etsy_shared_secret or joined):
        print()
        print(paint.warn("Next step: ") + (
            "add ETSY_SHARED_SECRET to your .env. Etsy rejects requests that\n"
            "  send the keystring on its own -- it needs keystring:shared_secret.\n"
            "  Both are at https://www.etsy.com/developers/your-apps (click the\n"
            "  eye icon to reveal the secret)."
        ))
        return 1

    if args.live:
        print()
        print(paint.dim("Testing a live Etsy call ..."))
        try:
            cache = Cache(settings.cache_dir, enabled=False)
            etsy = EtsyClient(settings.etsy_auth, cache)
            listings, count = etsy.search_active_listings("wax seal kit", limit=1)
            print(paint.good(
                f"Etsy OK -- {count:,} active listings match 'wax seal kit'."
            ))
        except ApiError as exc:
            print(paint.bad(f"Etsy call failed: {exc}"))
            return 1
        if settings.aliexpress_app_key and settings.aliexpress_app_secret:
            print(paint.dim("Testing a live AliExpress call ..."))
            try:
                ali = AliExpressClient(
                    settings.aliexpress_app_key,
                    settings.aliexpress_app_secret,
                    Cache(settings.cache_dir, enabled=False),
                    tracking_id=settings.aliexpress_tracking_id,
                    gateway=settings.aliexpress_gateway,
                    sign_method=settings.aliexpress_sign_method,
                )
                products = ali.search_products("wax seal kit", limit=2)
                print(paint.good(f"AliExpress OK -- {len(products)} products returned."))
            except ApiError as exc:
                print(paint.bad(f"AliExpress call failed: {exc}"))
                return 1
    return 0


def cmd_cache(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    cache = Cache(settings.cache_dir, enabled=True)
    if args.clear:
        removed = cache.clear()
        print(f"Cleared {removed} cached response(s) from {settings.cache_dir}")
        return 0
    files = sorted(settings.cache_dir.glob("*.json")) if settings.cache_dir.is_dir() else []
    total = sum(f.stat().st_size for f in files)
    print(f"{len(files)} cached response(s), {total / 1024:.1f} KB in {settings.cache_dir}")
    print(paint.dim("Use 'pf.py cache --clear' to empty it."))
    return 0


def cmd_demo(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    """Run the whole pipeline on bundled sample data -- no API keys needed.

    This exists so you can see what the output looks like, and confirm the
    maths works, before you have finished signing up for the APIs.
    """
    from .demo import run_demo

    results = run_demo(
        settings,
        min_profit=args.min_profit,
        max_candidates=args.top,
        etsy_only=args.etsy_only,
        min_match=args.min_match,
    )
    for result in results:
        print_keyword_result(result, settings, paint)
    print_comparison(results, settings, paint)
    save_outputs(results, [r.keyword for r in results], settings, args, "demo", paint)
    print()
    print(paint.warn("This was sample data, not live API results."))
    return 0


def cmd_serve(args: argparse.Namespace, settings: Settings, paint: Painter) -> int:
    """Run the web dashboard.

    The server reloads settings per request through this closure, so editing
    .env or switching store profiles in the page takes effect immediately --
    no restart.
    """
    from .server import serve

    default_profile = getattr(args, "profile", None)

    def load_settings(profile: str | None) -> Settings:
        return Settings.load(
            Path(args.env) if args.env else None,
            profile=profile or default_profile,
        )

    serve(load_settings, port=args.port, open_browser=not args.no_open)
    return 0


def print_disclaimer(paint: Painter) -> None:
    print()
    print(paint.dim(
        "Estimates only. Favorites measure interest, not sales. Profit excludes\n"
        "tax, duty, currency conversion, ads, returns and your time. Verify\n"
        "shipping and supplier quality on the product page, and check Etsy's\n"
        "current fees and reselling policies before you list anything."
    ))


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--top", type=int, default=15,
                        help="how many AliExpress matches to show per keyword (default 15)")
    parser.add_argument("--min-profit", type=float, default=0.0, metavar="USD",
                        help="hide matches earning less than this per sale")
    parser.add_argument("--min-match", type=float, default=0.0, metavar="SCORE",
                        help="hide AliExpress products scoring below this on "
                             "resemblance to the Etsy market (0-100; try 30)")
    parser.add_argument("--etsy-only", action="store_true",
                        help="skip AliExpress entirely (demand research only)")
    parser.add_argument("--no-cache", action="store_true",
                        help="ignore cached responses for this run")
    parser.add_argument("--refresh", action="store_true",
                        help="fetch fresh data and overwrite the cache")
    parser.add_argument("--cache-ttl", type=float, default=None, metavar="HOURS",
                        help="treat cached data older than this as stale")
    parser.add_argument("--csv", metavar="PATH", help="where to write the CSV")
    parser.add_argument("--html", metavar="PATH", help="where to write the HTML report")
    parser.add_argument("--no-save", action="store_true",
                        help="print to the terminal only, write no files")
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    add_profile_argument(parser)


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    """Allow --profile either before or after the subcommand.

    `SUPPRESS` is the trick: without it, a subcommand's unset --profile would
    overwrite one given before the subcommand with None. With it, the
    attribute is simply absent unless the user typed it, so whichever position
    they used survives.
    """
    parser.add_argument(
        "--profile", metavar="NAME", default=argparse.SUPPRESS,
        help="load per-store settings from .env.NAME on top of .env "
             "(e.g. --profile clothing). Reports go to reports/NAME/.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pf.py",
        description=(
            "Research craft-supply products to resell on Etsy, sourced from "
            "AliExpress. Uses only the official Etsy Open API v3 and AliExpress "
            "Affiliate API -- no scraping."
        ),
        epilog=(
            "Examples:\n"
            '  python pf.py check\n'
            '  python pf.py demo\n'
            '  python pf.py search "wax seal kit"\n'
            '  python pf.py search "resin mold" --min-profit 5 --top 10\n'
            '  python pf.py compare "wax seal kit" "resin mold" "leather stamp"\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"product-finder {__version__}")
    parser.add_argument("--env", metavar="PATH", help="use a different .env file")
    add_profile_argument(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="research one keyword")
    search.add_argument("keyword", nargs="+", help='e.g. "wax seal kit"')
    add_common_arguments(search)
    search.set_defaults(func=cmd_search)

    compare = sub.add_parser("compare", help="research several keywords and rank them")
    compare.add_argument("keywords", nargs="+", help="two or more keywords")
    compare.add_argument("--brief", action="store_true",
                         help="show only the comparison table, not each keyword's detail")
    add_common_arguments(compare)
    compare.set_defaults(func=cmd_compare)

    check = sub.add_parser("check", help="show what is configured and test your keys")
    check.add_argument("--live", action="store_true",
                       help="make one real API call to each service to prove the keys work")
    check.add_argument("--no-color", action="store_true")
    add_profile_argument(check)
    check.set_defaults(func=cmd_check)

    cache_cmd = sub.add_parser("cache", help="inspect or clear the local cache")
    cache_cmd.add_argument("--clear", action="store_true", help="delete all cached responses")
    cache_cmd.add_argument("--no-color", action="store_true")
    add_profile_argument(cache_cmd)
    cache_cmd.set_defaults(func=cmd_cache)

    serve_cmd = sub.add_parser(
        "serve", help="open the web dashboard in your browser"
    )
    serve_cmd.add_argument("--port", type=int, default=8765,
                           help="port to listen on (default 8765)")
    serve_cmd.add_argument("--no-open", action="store_true",
                           help="do not open a browser window automatically")
    serve_cmd.add_argument("--no-color", action="store_true")
    add_profile_argument(serve_cmd)
    serve_cmd.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="run on bundled sample data, no API keys needed")
    add_common_arguments(demo)
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paint = Painter(enabled=False if getattr(args, "no_color", False) else None)

    try:
        settings = Settings.load(
            Path(args.env) if args.env else None,
            profile=getattr(args, "profile", None),
        )
        return args.func(args, settings, paint)
    except SettingsError as exc:
        print(paint.bad("Configuration problem:"), file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(paint.bad("API error:"), file=sys.stderr)
        print(f"  {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
