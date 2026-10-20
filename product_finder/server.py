"""A small local web dashboard.

Run `python pf.py serve` and the whole tool becomes a web page instead of a
command line. It is the same engine underneath -- the browser just calls a
few JSON endpoints that wrap `analysis.py`.

Security notes, because this serves your API keys' capabilities:

  * It binds to 127.0.0.1 only, so nothing outside your computer can reach it.
    Do not change that to 0.0.0.0 unless you understand what you are exposing.
  * It never echoes your keys back to the browser -- only whether they are set.
  * File serving is restricted to the reports folder, with the path resolved
    and checked, so a crafted URL cannot walk out of it.

Still standard library only: `http.server` is built into Python.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .aliexpress import AliExpressClient
from .analysis import KeywordResult, discover_keywords, research_keyword
from .cache import Cache
from .config import PROJECT_ROOT, Settings, SettingsError
from .economics import max_sourcing_cost
from .etsy import EtsyClient
from .http import ApiError
from .report import default_paths, write_csv, write_html

# Every report ever written lives under here, whatever a profile sets
# OUTPUT_DIR to. The server serves from this folder and nowhere else.
REPORTS_ROOT = (PROJECT_ROOT / "reports").resolve()

MAX_BODY_BYTES = 64 * 1024
MAX_KEYWORDS = 12


def available_profiles() -> list[str]:
    """Every `.env.<name>` sitting next to the project, minus the template."""
    names = []
    for path in sorted(PROJECT_ROOT.glob(".env.*")):
        suffix = path.name[len(".env.") :]
        if suffix and suffix != "example":
            names.append(suffix)
    return names


def _result_to_dict(result: KeywordResult, settings: Settings) -> dict[str, Any]:
    """Flatten a KeywordResult into JSON the dashboard can render."""
    demand = result.demand
    best = result.best
    return {
        "keyword": result.keyword,
        "nicheScore": result.niche_score,
        "sourcingChecked": result.sourcing_checked,
        "opportunityScore": demand.opportunity_score,
        "demandScore": demand.demand_score,
        "competitionScore": demand.competition_score,
        "listingCount": demand.listing_count,
        "sampled": demand.sampled,
        "meanFavorites": demand.mean_favorites,
        "topFavorites": demand.top_favorites,
        "uniqueShops": demand.unique_shops,
        "typicalPrice": demand.typical_price,
        "priceP25": demand.price_p25,
        "priceP75": demand.price_p75,
        "flags": demand.flags,
        "topTags": [{"tag": t, "count": c} for t, c in demand.top_tags],
        "categoryMix": [
            {"label": label, "share": share} for label, share in demand.category_mix
        ],
        "mainCategory": demand.main_category,
        "mainCategoryShare": demand.main_category_share,
        "warnings": result.warnings,
        "breakEven": max_sourcing_cost(demand.typical_price, settings.fees)
        if demand.typical_price > 0
        else None,
        "budget20": max_sourcing_cost(demand.typical_price, settings.fees, 0.20)
        if demand.typical_price > 0
        else None,
        "bestProfit": best.profit.profit if best else None,
        "bestMargin": best.profit.margin if best else None,
        "candidates": [
            {
                "title": c.product.title,
                "url": c.product.url,
                "price": c.product.price,
                "shipping": c.product.shipping,
                "shippingIsEstimate": c.product.shipping_is_estimate,
                "landedCost": c.product.landed_cost,
                "orders": c.product.orders,
                "rating": c.product.rating,
                "supplierScore": c.supplier_score,
                "matchScore": c.match_score,
                "fees": c.profit.total_fees,
                "profit": c.profit.profit,
                "margin": c.profit.margin,
                "isViable": c.profit.is_viable,
            }
            for c in result.candidates
        ],
        "topListings": [
            {
                "title": item.title,
                "url": item.url,
                "shop": item.shop_name,
                "price": item.price,
                "favorites": item.num_favorers,
            }
            for item in sorted(
                result.listings, key=lambda i: i.num_favorers, reverse=True
            )[:8]
        ],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """Routes requests. One instance per request, as http.server does it."""

    server_version = "product-finder"

    def __init__(self, *args, settings_loader=None, **kwargs):
        self._load_settings = settings_loader
        super().__init__(*args, **kwargs)

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        # The default logs every request to stderr, which buries the one line
        # that matters (the URL to open). Keep errors only.
        if args and str(args[0]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This page talks only to itself; refuse to be framed by anything.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The browser navigated away mid-response; harmless.

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(
            status,
            json.dumps(payload, default=str).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/profiles":
            self._handle_profiles()
        elif path.startswith("/reports/"):
            self._serve_report(path)
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path == "/api/research":
                self._handle_research()
            elif path == "/api/discover":
                self._handle_discover()
            else:
                self._send_json(404, {"error": "Not found"})
        except SettingsError as exc:
            self._send_json(400, {"error": str(exc)})
        except ApiError as exc:
            self._send_json(502, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - never kill the server
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _handle_profiles(self) -> None:
        try:
            settings = self._load_settings(None)
            configured = {
                "etsy": bool(settings.etsy_api_key and settings.etsy_shared_secret),
                "aliexpress": bool(
                    settings.aliexpress_app_key and settings.aliexpress_app_secret
                ),
            }
        except SettingsError:
            configured = {"etsy": False, "aliexpress": False}
        self._send_json(
            200, {"profiles": available_profiles(), "configured": configured}
        )

    def _clients(self, settings: Settings, no_cache: bool):
        cache = Cache(
            settings.cache_dir, settings.cache_ttl_hours, enabled=not no_cache
        )
        settings.require_etsy()
        etsy = EtsyClient(settings.etsy_auth, cache, currency=settings.currency)
        ali = None
        if settings.aliexpress_app_key and settings.aliexpress_app_secret:
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
        return etsy, ali

    def _handle_discover(self) -> None:
        body = self._read_json()
        seed = str(body.get("seed") or "").strip()
        if not seed:
            self._send_json(400, {"error": "Give me a starting keyword."})
            return
        settings = self._load_settings(body.get("profile") or None)
        etsy, _ = self._clients(settings, bool(body.get("noCache")))
        found = discover_keywords(seed, settings, etsy)
        self._send_json(
            200,
            {
                "seed": seed,
                "suggestions": [{"keyword": k, "count": c} for k, c in found],
            },
        )

    def _handle_research(self) -> None:
        body = self._read_json()
        keywords = [
            str(k).strip()
            for k in (body.get("keywords") or [])
            if str(k).strip()
        ][:MAX_KEYWORDS]
        if not keywords:
            self._send_json(400, {"error": "Give me at least one keyword."})
            return

        profile = body.get("profile") or None
        settings = self._load_settings(profile)
        etsy, ali = self._clients(settings, bool(body.get("noCache")))

        try:
            min_profit = float(body.get("minProfit") or 0)
        except (TypeError, ValueError):
            min_profit = 0.0
        try:
            top = max(1, min(50, int(body.get("top") or 15)))
        except (TypeError, ValueError):
            top = 15

        results: list[KeywordResult] = []
        errors: list[str] = []
        for keyword in keywords:
            try:
                results.append(
                    research_keyword(
                        keyword,
                        settings,
                        etsy,
                        ali,
                        refresh=bool(body.get("refresh")),
                        min_profit=min_profit,
                        max_candidates=top,
                        min_match=float(body.get("minMatch") or 0),
                    )
                )
            except ApiError as exc:
                errors.append(f"{keyword}: {exc}")

        saved: dict[str, str] = {}
        if results and body.get("save"):
            mode = "compare" if len(results) > 1 else "search"
            csv_path, html_path = default_paths(keywords, settings.output_dir, mode)
            write_csv(results, csv_path)
            write_html(results, html_path, settings, mode=mode)
            saved = {
                "csv": _report_url(csv_path, settings),
                "html": _report_url(html_path, settings),
            }

        results.sort(key=lambda r: r.niche_score, reverse=True)
        self._send_json(
            200,
            {
                "results": [_result_to_dict(r, settings) for r in results],
                "errors": errors,
                "saved": saved,
                "profile": profile,
                "aliexpressActive": ali is not None,
            },
        )

    def _serve_report(self, path: str) -> None:
        """Serve a saved report, and nothing outside the reports folder."""
        relative = unquote(path[len("/reports/") :])
        target = (REPORTS_ROOT / relative).resolve()

        # Resolve first, THEN check containment: that is what defeats `../`,
        # URL-encoded `%2e%2e`, and symlinks pointing out of the folder.
        try:
            target.relative_to(REPORTS_ROOT)
        except ValueError:
            self._send_json(403, {"error": "Outside the reports folder"})
            return
        if not target.is_file() or target.suffix not in (".html", ".csv"):
            self._send_json(404, {"error": "No such report"})
            return

        kind = (
            "text/html; charset=utf-8"
            if target.suffix == ".html"
            else "text/csv; charset=utf-8"
        )
        self._send(200, target.read_bytes(), kind)


def _report_url(path: Path, settings: Settings) -> str:
    """Turn a saved report path into a URL this server can serve.

    Returns "" when OUTPUT_DIR points somewhere outside the reports folder,
    because the server deliberately refuses to serve anything from there.
    """
    try:
        return "/reports/" + path.resolve().relative_to(REPORTS_ROOT).as_posix()
    except ValueError:
        return ""


def serve(
    settings_loader,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start the dashboard and block until Ctrl+C."""
    handler = partial(DashboardHandler, settings_loader=settings_loader)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{httpd.server_address[1]}"

    print(f"product-finder dashboard running at {url}")
    print("  Only your computer can reach it. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


# The dashboard itself. Kept as one self-contained string: no build step, no
# CDN, nothing to install, and it works offline.
DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>product-finder</title>
<style>
:root {
  --bg:#fbfaf8; --card:#fff; --ink:#1d1b19; --muted:#6b6560; --line:#e6e1da;
  --good:#1d7a4c; --bad:#b03a2e; --warn:#9a6a00; --accent:#7a4a2b;
  --accent-ink:#fff; --chip:#f3efe9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#17161a; --card:#201e23; --ink:#f2efe9; --muted:#a39d96; --line:#35313a;
    --good:#58c08a; --bad:#e8806f; --warn:#e0b24d; --accent:#d8a87c;
    --accent-ink:#201e23; --chip:#2a272e;
  }
}
:root[data-theme="dark"] {
  --bg:#17161a; --card:#201e23; --ink:#f2efe9; --muted:#a39d96; --line:#35313a;
  --good:#58c08a; --bad:#e8806f; --warn:#e0b24d; --accent:#d8a87c;
  --accent-ink:#201e23; --chip:#2a272e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 80px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-bottom:6px}
h1{font-size:1.6rem;margin:0;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:.86rem;margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin-bottom:20px}
label{display:block;font-size:.76rem;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);font-weight:600;margin-bottom:6px}
input,select,textarea,button{font:inherit;color:inherit}
input,select,textarea{width:100%;background:var(--bg);border:1px solid var(--line);
  border-radius:8px;padding:9px 11px}
textarea{min-height:96px;resize:vertical;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:.9rem}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
.row{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px}
.row>div{flex:1 1 150px;min-width:0}
button{background:var(--accent);color:var(--accent-ink);border:0;border-radius:8px;
  padding:10px 18px;font-weight:600;cursor:pointer}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}
button:disabled{opacity:.5;cursor:not-allowed}
button:hover:not(:disabled){filter:brightness(1.08)}
.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.chip{display:inline-block;font-size:.74rem;text-transform:uppercase;letter-spacing:.04em;
  padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--muted);
  background:var(--chip);margin:0 5px 5px 0}
.chip.hit{color:var(--good);border-color:var(--good);font-weight:650}
.chip.risk{color:var(--bad);border-color:var(--bad)}
.chip.pick{cursor:pointer;color:var(--ink)}
.chip.pick:hover{border-color:var(--accent);color:var(--accent)}
.chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:.87rem}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:var(--chip)}
.good{color:var(--good);font-weight:650}.bad{color:var(--bad)}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.stats{display:flex;flex-wrap:wrap;gap:16px 26px;margin:12px 0 2px;color:var(--muted);font-size:.84rem}
.stats b{display:block;color:var(--ink);font-size:1rem;font-weight:650}
.note{background:color-mix(in srgb,var(--warn) 12%,transparent);
  border-left:3px solid var(--warn);padding:9px 13px;border-radius:6px;font-size:.85rem;margin:10px 0}
.err{background:color-mix(in srgb,var(--bad) 12%,transparent);border-left:3px solid var(--bad)}
.muted{color:var(--muted);font-size:.84rem}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--line);
  border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;
  vertical-align:-2px;margin-right:7px}
@keyframes spin{to{transform:rotate(360deg)}}
.hidden{display:none}
.scorebar{height:5px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:5px;min-width:54px}
.scorebar i{display:block;height:100%;background:var(--accent)}
details{margin-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:.84rem}
@media(max-width:720px){table{display:block;overflow-x:auto;white-space:nowrap}}
</style></head>
<body><div class="wrap">

<header>
  <h1>product-finder</h1>
  <span class="muted" id="status"></span>
</header>
<p class="sub">Etsy demand research and AliExpress sourcing, from the official APIs.</p>

<div class="card">
  <div class="row">
    <div>
      <label for="profile">Store profile</label>
      <select id="profile"><option value="">Default (craft supplies)</option></select>
    </div>
    <div>
      <label for="minProfit">Min profit ($)</label>
      <input id="minProfit" type="number" value="0" min="0" step="0.5">
    </div>
    <div>
      <label for="minMatch">Min match (0-100)</label>
      <input id="minMatch" type="number" value="0" min="0" max="100" step="5">
    </div>
    <div>
      <label for="top">Matches per keyword</label>
      <input id="top" type="number" value="15" min="1" max="50">
    </div>
  </div>

  <label for="seed">Find keywords for me &mdash; start from one idea</label>
  <div class="row">
    <div style="flex:3 1 260px">
      <input id="seed" placeholder="linen dress" aria-label="Seed keyword">
    </div>
    <div style="flex:0 0 auto">
      <button class="ghost" id="discoverBtn" type="button">Discover</button>
    </div>
  </div>
  <div id="suggestions" class="hidden">
    <p class="muted" style="margin:4px 0 8px">
      Tags real sellers use in this market. Click to add, then Research.
    </p>
    <div id="chips"></div>
  </div>
</div>

<div class="card">
  <label for="keywords">Keywords to research &mdash; one per line</label>
  <textarea id="keywords" placeholder="linen jumpsuit&#10;nursing dress&#10;cottagecore blouse"></textarea>
  <div class="actions" style="margin-top:12px">
    <button id="researchBtn" type="button">Research</button>
    <label style="display:flex;align-items:center;gap:6px;text-transform:none;
      letter-spacing:0;font-size:.85rem;font-weight:400;margin:0">
      <input type="checkbox" id="save" checked style="width:auto"> Save CSV + HTML
    </label>
    <label style="display:flex;align-items:center;gap:6px;text-transform:none;
      letter-spacing:0;font-size:.85rem;font-weight:400;margin:0">
      <input type="checkbox" id="refresh" style="width:auto"> Ignore cache
    </label>
  </div>
</div>

<div id="messages"></div>
<div id="output"></div>

</div>
<script>
const $ = (id) => document.getElementById(id);
const money = (v) => v === null || v === undefined ? "--"
  : (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
const num = (v) => (v ?? 0).toLocaleString();
const pct = (v) => v === null || v === undefined ? "--" : Math.round(v * 100) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

let busy = false;
function setBusy(on, what) {
  busy = on;
  $("researchBtn").disabled = on;
  $("discoverBtn").disabled = on;
  $("status").innerHTML = on ? '<span class="spinner"></span>' + esc(what) : "";
}
function message(text, isError) {
  $("messages").innerHTML =
    '<div class="note ' + (isError ? "err" : "") + '">' + esc(text) + "</div>";
}
function clearMessages() { $("messages").innerHTML = ""; }

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({error: "Bad response from the server"}));
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function keywordList() {
  return $("keywords").value.split("\n").map(s => s.trim()).filter(Boolean);
}
function addKeyword(kw) {
  const have = keywordList();
  if (have.includes(kw)) return;
  $("keywords").value = have.concat([kw]).join("\n");
}

$("discoverBtn").onclick = async () => {
  const seed = $("seed").value.trim();
  if (!seed) { message("Type one keyword to start from."); return; }
  clearMessages();
  setBusy(true, "asking Etsy what this market calls itself...");
  try {
    const data = await api("/api/discover", {seed, profile: $("profile").value});
    const chips = $("chips");
    if (!data.suggestions.length) {
      message("No related tags found. Try a broader starting keyword.");
      $("suggestions").classList.add("hidden");
    } else {
      chips.innerHTML = data.suggestions.map(s =>
        '<span class="chip pick" data-kw="' + esc(s.keyword) + '">' +
        esc(s.keyword) + ' <span class="muted">' + s.count + '</span></span>'
      ).join("");
      chips.querySelectorAll(".chip").forEach(chip => {
        chip.onclick = () => { addKeyword(chip.dataset.kw); chip.classList.add("on"); };
      });
      $("suggestions").classList.remove("hidden");
    }
  } catch (e) { message(e.message, true); }
  setBusy(false);
};

$("researchBtn").onclick = async () => {
  const keywords = keywordList();
  if (!keywords.length) { message("Add at least one keyword."); return; }
  clearMessages();
  $("output").innerHTML = "";
  setBusy(true, "researching " + keywords.length +
    (keywords.length === 1 ? " keyword" : " keywords") + "... this can take a minute");
  try {
    const data = await api("/api/research", {
      keywords,
      profile: $("profile").value,
      minProfit: parseFloat($("minProfit").value) || 0,
      minMatch: parseFloat($("minMatch").value) || 0,
      top: parseInt($("top").value) || 15,
      save: $("save").checked,
      refresh: $("refresh").checked,
    });
    render(data);
  } catch (e) { message(e.message, true); }
  setBusy(false);
};

function flagChip(f) {
  const cls = f === f.toUpperCase() ? "hit"
    : ["saturated","dominated by few shops","low price ceiling",
       "mixed categories"].includes(f) ? "risk" : "";
  return '<span class="chip ' + cls + '">' + esc(f) + "</span>";
}

function render(data) {
  const out = [];
  if (data.errors.length) {
    out.push('<div class="note err">' + data.errors.map(esc).join("<br>") + "</div>");
  }
  if (!data.results.length) { $("output").innerHTML = out.join(""); return; }

  if (data.results.length > 1) {
    const moneyCol = data.results.some(r => r.bestProfit !== null)
      ? "Best profit" : "Budget @20%";
    out.push('<div class="card"><h2 style="margin:0 0 4px;font-size:1.1rem">Ranked</h2>' +
      '<p class="muted" style="margin:0">Click a row to jump to its detail.</p><table><thead><tr>' +
      "<th>#</th><th>Keyword</th><th class='num'>Score</th><th class='num'>Competing</th>" +
      "<th class='num'>Avg favs</th><th class='num'>Typical</th><th class='num'>" +
      moneyCol + "</th><th class='num'>Margin</th><th>Flags</th></tr></thead><tbody>" +
      data.results.map((r, i) =>
        '<tr class="clickable" data-go="kw' + i + '"><td class="num">' + (i + 1) + "</td>" +
        "<td><strong>" + esc(r.keyword) + "</strong></td>" +
        '<td class="num">' + Math.round(r.nicheScore) +
          '<div class="scorebar"><i style="width:' + r.nicheScore + '%"></i></div></td>' +
        '<td class="num">' + num(r.listingCount) + "</td>" +
        '<td class="num">' + num(Math.round(r.meanFavorites)) + "</td>" +
        '<td class="num">' + money(r.typicalPrice) + "</td>" +
        '<td class="num">' + money(r.bestProfit !== null ? r.bestProfit : r.budget20) + "</td>" +
        '<td class="num">' + pct(r.bestMargin) + "</td>" +
        "<td>" + r.flags.map(flagChip).join("") + "</td></tr>"
      ).join("") + "</tbody></table>" +
      (moneyCol === "Budget @20%"
        ? '<p class="muted" style="margin:10px 0 0">Budget @20% = the most you can pay ' +
          "a supplier (item + shipping) and still keep a 20% margin.</p>"
        : "") +
      "</div>");
  }

  data.results.forEach((r, i) => {
    const label = r.sourcingChecked ? "niche score" : "Etsy-only score";
    let block = '<div class="card" id="kw' + i + '">' +
      '<div style="display:flex;flex-wrap:wrap;align-items:baseline;gap:10px">' +
      '<h2 style="margin:0;font-size:1.15rem">' + esc(r.keyword) + "</h2>" +
      '<span style="color:var(--accent);font-weight:700">' + label + " " +
      Math.round(r.nicheScore) + "/100</span></div>" +
      '<div class="stats">' +
      stat("Competing", num(r.listingCount)) + stat("Sampled", r.sampled) +
      stat("Avg favorites", num(Math.round(r.meanFavorites))) +
      stat("Top listing", num(r.topFavorites) + " favs") +
      stat("Shops", r.uniqueShops) + stat("Typical price", money(r.typicalPrice)) +
      stat("Price range", money(r.priceP25) + " - " + money(r.priceP75)) +
      stat("Demand", Math.round(r.demandScore) + "/100") +
      stat("Low competition", Math.round(r.competitionScore) + "/100") +
      "</div><div style='margin-top:10px'>" + r.flags.map(flagChip).join("") + "</div>";

    if (r.categoryMix.length) {
      block += '<p class="muted" style="margin:12px 0 0"><strong>What these ' +
        "listings actually are:</strong> " +
        r.categoryMix.slice(0, 4).map(c =>
          esc(c.label) + " " + Math.round(c.share) + "%").join(" &middot; ") + "</p>";
      if (r.flags.includes("mixed categories")) {
        block += '<div class="note err">Only ' + Math.round(r.mainCategoryShare) +
          "% of this keyword's listings are " + esc(r.mainCategory) +
          ". The scores describe that whole mixture, not one product type &mdash; " +
          "check it is the market you mean before acting on them.</div>";
      }
    }

    r.warnings.forEach(w => { block += '<div class="note">' + esc(w) + "</div>"; });

    if (!r.candidates.length && r.budget20 !== null) {
      const tight = r.budget20 < 4;
      block += '<p class="muted" style="margin:12px 0 0">Selling at the ' +
        money(r.typicalPrice) + " median, your landed cost must stay under " +
        "<strong>" + money(r.breakEven) + "</strong> to break even, or " +
        '<strong class="' + (tight ? "bad" : "good") + '">' + money(r.budget20) +
        "</strong> for a 20% margin.</p>";
      if (tight) {
        block += '<div class="note">That is a very tight budget once AliExpress ' +
          "shipping is counted. Cheap niches look good on demand and rarely " +
          "survive the fees.</div>";
      }
    }

    if (r.candidates.length) {
      block += "<table><thead><tr><th>AliExpress product</th><th class='num'>Cost</th>" +
        "<th class='num'>Ship</th><th class='num'>Landed</th><th class='num'>Orders</th>" +
        "<th class='num'>Match</th>" +
        "<th class='num'>Rating</th><th class='num'>Supplier</th><th class='num'>Fees</th>" +
        "<th class='num'>Profit</th><th class='num'>Margin</th></tr></thead><tbody>" +
        r.candidates.map(c =>
          "<tr><td><a href='" + esc(c.url) + "' target='_blank' rel='noopener noreferrer'>" +
          esc(c.title.slice(0, 80)) + "</a></td>" +
          "<td class='num'>" + money(c.price) + "</td>" +
          "<td class='num'>" + (c.shippingIsEstimate ? "~" : "") + money(c.shipping) + "</td>" +
          "<td class='num'>" + money(c.landedCost) + "</td>" +
          "<td class='num'>" + num(c.orders) + "</td>" +
          "<td class='num " + (c.matchScore >= 35 ? "good" : "bad") + "'>" +
            Math.round(c.matchScore) + "</td>" +
          "<td class='num'>" + c.rating.toFixed(1) + "</td>" +
          "<td class='num'>" + Math.round(c.supplierScore) + "</td>" +
          "<td class='num'>" + money(c.fees) + "</td>" +
          "<td class='num " + (c.isViable ? "good" : "bad") + "'>" + money(c.profit) + "</td>" +
          "<td class='num " + (c.isViable ? "good" : "bad") + "'>" + pct(c.margin) + "</td></tr>"
        ).join("") + "</tbody></table>";
    }

    if (r.topListings.length) {
      block += "<details><summary>Most-favorited Etsy listings and common tags</summary>" +
        "<table><thead><tr><th>Listing</th><th>Shop</th><th class='num'>Price</th>" +
        "<th class='num'>Favorites</th></tr></thead><tbody>" +
        r.topListings.map(l =>
          "<tr><td><a href='" + esc(l.url) + "' target='_blank' rel='noopener noreferrer'>" +
          esc(l.title.slice(0, 70)) + "</a></td><td>" + esc(l.shop) + "</td>" +
          "<td class='num'>" + money(l.price) + "</td>" +
          "<td class='num'>" + num(l.favorites) + "</td></tr>"
        ).join("") + "</tbody></table>" +
        "<p class='muted' style='margin-top:10px'>" +
        r.topTags.map(t => '<span class="chip pick" data-kw="' + esc(t.tag) + '">' +
          esc(t.tag) + " " + t.count + "</span>").join("") + "</p></details>";
    }
    block += "</div>";
    out.push(block);
  });

  if (data.saved && data.saved.html) {
    out.push('<p class="muted">Saved: <a href="' + data.saved.html +
      '" target="_blank">HTML report</a> &middot; <a href="' + data.saved.csv +
      '">CSV</a></p>');
  }
  out.push('<p class="muted">Estimates only. Favorites measure interest, not sales. ' +
    "Profit excludes tax, duty, currency conversion, ads, returns and your time. " +
    "Check Etsy's current fees and its policies on what you may list.</p>");

  $("output").innerHTML = out.join("");
  document.querySelectorAll("tr[data-go]").forEach(tr => {
    tr.onclick = () => $(tr.dataset.go).scrollIntoView({behavior: "smooth"});
  });
  document.querySelectorAll("#output .chip.pick").forEach(chip => {
    chip.onclick = () => { addKeyword(chip.dataset.kw); chip.classList.add("on"); };
  });
}
function stat(label, value) {
  return "<div>" + esc(label) + "<b>" + value + "</b></div>";
}

(async function init() {
  try {
    const res = await fetch("/api/profiles");
    const data = await res.json();
    data.profiles.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p; opt.textContent = p;
      $("profile").appendChild(opt);
    });
    if (!data.configured.etsy) {
      message("Your Etsy key is not set up yet. Add ETSY_API_KEY and " +
        "ETSY_SHARED_SECRET to your .env file, then reload this page.", true);
    } else if (!data.configured.aliexpress) {
      message("AliExpress keys are not set, so you will get Etsy demand " +
        "research and sourcing budgets, but no supplier prices or profit figures.");
    }
  } catch (e) { message("Could not reach the server: " + e.message, true); }
})();
</script>
</body></html>
"""
