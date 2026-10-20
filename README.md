# product-finder

A command-line tool for researching craft-supply products to resell on Etsy,
sourced from AliExpress.

You give it a keyword like `wax seal kit`. It asks Etsy how many people are
selling that, how popular those listings are, and what they charge. Then it
asks AliExpress what the same thing costs to buy, subtracts Etsy's fees, and
tells you what you would actually make per sale. It ranks the results, and
saves a spreadsheet and a web page you can read later.

It uses **only official APIs** — the Etsy Open API v3 and the AliExpress
Affiliate API. There is no web scraping anywhere, which means nothing here
breaks when a website changes its layout, and nothing violates either site's
terms by pretending to be a browser.

---

## Table of contents

1. [What you need before you start](#1-what-you-need-before-you-start)
2. [Try it right now, with no API keys](#2-try-it-right-now-with-no-api-keys)
3. [Step 2: Get your Etsy API key](#3-step-2-get-your-etsy-api-key)
4. [Step 3: Get your AliExpress API keys](#4-step-3-get-your-aliexpress-api-keys)
5. [Step 4: Put your keys in the .env file](#5-step-4-put-your-keys-in-the-env-file)
6. [Using the tool](#6-using-the-tool)
7. [Reading the output](#7-reading-the-output)
8. [How the numbers are calculated](#8-how-the-numbers-are-calculated)
9. [Changing the settings](#9-changing-the-settings)
9b. [Running more than one store](#9b-running-more-than-one-store)
10. [The cache](#10-the-cache)
11. [Troubleshooting](#11-troubleshooting)
12. [How the code is organised](#12-how-the-code-is-organised)
13. [Honest limitations — please read](#13-honest-limitations--please-read)

---

## 1. What you need before you start

**Python 3.10 or newer.** That is it. There are **no packages to install.**

Check your Python version by opening a terminal (on Windows, press the Start
key, type `powershell`, press Enter) and running:

```bash
python --version
```

If you see `Python 3.10` or higher, you are ready. If the command is not found,
install Python from [python.org/downloads](https://www.python.org/downloads/)
and tick **"Add Python to PATH"** during setup.

Now move into this project's folder. In the terminal, type `cd ` (with a space)
and then drag the `product-finder` folder onto the terminal window and press
Enter.

> **Why no packages?** A normal Python project would use libraries like
> `requests` for web calls and `rich` for pretty tables. This one deliberately
> uses only what ships with Python, so you never hit an install problem while
> you are learning. The trade-off is a bit more code in `http.py` and
> `table.py`, which is commented so you can see what those libraries do for you.

---

## 2. Try it right now, with no API keys

Signing up for API access takes a while — AliExpress in particular may take
days to approve you. So the tool ships with sample data so you can see exactly
what it does first:

```bash
python pf.py demo
```

You will get the full experience: ranked tables in the terminal, a niche
comparison, and a CSV plus an HTML report saved into a new `reports/` folder.
Open the `.html` file in your browser.

**The numbers in `demo` are invented.** They are shaped exactly like real API
responses and run through the exact same maths, so it is a true preview of the
tool — but do not make any business decision from demo output.

---

## 3. Step 2: Get your Etsy API key

### 3a. Choose which kind of app to register

Etsy offers two self-service routes, and **the one you want depends on whether
you already have a shop**:

| | **Seller App** | **Personal App** |
| --- | --- | --- |
| Who can get it | Anyone with an **active Etsy shop** in good standing | Any registered developer, **no shop needed** |
| Approval | Automated, **within minutes** | Deeper manual review, **no published wait time** |
| What it can read | **Your own shop only** | Beyond your own shop, at limited scale |
| Good for this tool? | **No** — this tool searches the whole marketplace | **Yes** |

Because product-finder searches *all* active listings rather than your own
shop, you need a **Personal App**. Be aware that this is the slower route and
goes through a real review. Run `python pf.py demo` while you wait.

### 3b. Register

1. **Sign in to Etsy** at [etsy.com](https://www.etsy.com) with a normal
   account.

2. Go to **[etsy.com/developers/register](https://www.etsy.com/developers/register)**
   and choose **Create a personal app**.

   (The sibling route, if you do have a shop and only want your own data, is
   [etsy.com/developers/register-seller-app](https://www.etsy.com/developers/register-seller-app).)

3. **Fill in the form.** Etsy asks what you are building and reviews it, so be
   honest and specific — vague applications get rejected. Something like:

   > A personal command-line research tool. It reads active public listings via
   > the Open API v3 listings search to analyse pricing and demand in
   > craft-supply categories, to help me decide what to sell in my own shop.
   > Read-only, results are not republished or shared, personal use only.

   - Will you charge money for it? **No.**
   - Do you need write access? **No** — read-only is all this tool uses.

4. **Wait for approval.** Your key exists immediately but is **inert until
   approved** — Etsy's docs say plainly: *"Your API key is not active until it
   has been approved."* The status shows in *Manage Your Apps*.

### 3c. Copy BOTH credentials

Once approved, go to
**[etsy.com/developers/your-apps](https://www.etsy.com/developers/your-apps)**.
Your app shows two values, and **you need both**:

- **Keystring** — visible, e.g. `a1b2c3d4e5f6g7h8i9j0k1l2`
- **Shared secret** — hidden. **Click the eye / visibility icon to reveal it.**

> ### Both? Yes — this is the mistake everyone makes
>
> Etsy's `x-api-key` header does not take the keystring on its own. It takes
> the two values joined with a colon:
>
> ```
> x-api-key: <keystring>:<shared_secret>
> ```
>
> Send the keystring alone and Etsy replies with a **403** and the message
> *"Invalid API key: should be in the format 'keystring:shared_secret'"*.
> This tool joins them for you — just put each in its own variable in `.env`.
>
> Keep the shared secret secret. It is not a public identifier.

> **Why no OAuth login flow?** Etsy requires the API key on *every* request,
> and additionally an OAuth 2.0 token **only** for endpoints that read private
> user data or write something. The listing search this tool uses does neither,
> so the API key alone is enough — which is why this is a good first API to
> learn on.

---

## 4. Step 3: Get your AliExpress API keys

This one is more involved and approval is slower. The tool still works
without it (you get Etsy demand research only), so do not let this block you.

1. Go to the **AliExpress Open Platform** at
   **[openservice.aliexpress.com](https://openservice.aliexpress.com)** and
   create a developer account, or sign in with your existing AliExpress
   account.

2. You will likely be asked to **join the AliExpress Affiliate programme**
   first, at [portals.aliexpress.com](https://portals.aliexpress.com). The
   affiliate product-search API is granted to affiliates. Signing up is free.
   You may be asked for a website, a social account, or a description of how
   you will promote products.

3. In the Open Platform **console**, create an **app**:
   - App type: choose the **self-developed / personal** option.
   - Describe it as a personal product-research tool.

4. **Request access to the Affiliate API.** In the console, find your app's
   permissions or API list and request the **aliexpress.affiliate.*** family —
   specifically **`aliexpress.affiliate.product.query`**, which is the one this
   tool calls. Approval can take anywhere from a day to a couple of weeks, and
   it is sometimes refused for accounts with no promotion history.

5. Once the app exists, open **App Management** and copy:
   - **App Key** (a number, e.g. `503124`)
   - **App Secret** (a long string)

6. **Optional: your Tracking ID.** In the affiliate portal, under tracking or
   ad-space settings, you may have a tracking ID like `default` or
   `mytracking`. If you set it, the product links in your reports become your
   affiliate links. Leave it blank if you do not have one or do not want that.

> **Why AliExpress needs two values when Etsy needs one:** AliExpress does not
> accept a plain key. Instead, every request is *signed*: the tool takes all
> the parameters it is about to send, sorts them, glues them into one long
> string, and hashes that string together with your App Secret. It sends the
> resulting hash as `sign`. The server repeats the calculation and compares.
> Your secret therefore proves the request is yours **without ever travelling
> over the internet.** You can read the ten-line implementation in
> `product_finder/aliexpress.py`, in the `sign_params` function.

---

## 5. Step 4: Put your keys in the `.env` file

API keys are passwords. They must never go in your code, because code gets
shared, committed to GitHub, and pasted into forums. Instead they live in a
file called `.env` that stays on your computer.

**Make your `.env` by copying the example:**

On Windows PowerShell:

```bash
Copy-Item .env.example .env
```

On macOS or Linux:

```bash
cp .env.example .env
```

Now open `.env` in any text editor (Notepad is fine) and paste your keys in:

```
ETSY_API_KEY=a1b2c3d4e5f6g7h8i9j0k1l2
ETSY_SHARED_SECRET=a1b2c3d4e5
ALIEXPRESS_APP_KEY=503124
ALIEXPRESS_APP_SECRET=your_long_secret_here
```

Note `ETSY_SHARED_SECRET` — see the warning in the previous section. Do not
join them yourself with a colon; the tool does that. (If you already pasted a
combined `keystring:shared_secret` into `ETSY_API_KEY`, that works too.)

**Rules for `.env`:**

- No quotes needed, and no spaces around the `=`.
- Do not commit it, email it, or paste it into a chat. It is already listed in
  `.gitignore` so Git will ignore it.
- `.env.example` is the safe one to share — it has placeholders, not secrets.
- If you ever think a key leaked, regenerate it in the Etsy or AliExpress
  console immediately.

**Now confirm it worked:**

```bash
python pf.py check
```

That prints what is configured and what is missing, without calling any API.
When it looks right, prove the keys actually work with one real call each:

```bash
python pf.py check --live
```

---

## 6. Using the tool

### Research one keyword

```bash
python pf.py search "wax seal kit"
```

Always put the keyword in **double quotes** if it has spaces.

### Compare several niches against each other

```bash
python pf.py compare "wax seal kit" "resin mold" "leather stamp set"
```

This researches each keyword and then ranks them, so you can see which niche is
the best bet rather than judging them one at a time. Add `--brief` to skip the
per-keyword detail and see only the comparison table.

### Useful options

| Option | What it does |
| --- | --- |
| `--top 10` | Show 10 AliExpress matches per keyword instead of 15 |
| `--min-profit 5` | Hide any product that would earn under $5 per sale |
| `--etsy-only` | Skip AliExpress entirely — demand research only |
| `--csv mine.csv` | Choose where the CSV goes |
| `--html mine.html` | Choose where the HTML report goes |
| `--no-save` | Print to the terminal only, write no files |
| `--refresh` | Ignore the cache and fetch fresh data |
| `--no-cache` | Do not read *or* write the cache this run |
| `--no-color` | Plain text, no colours |

Every command has built-in help:

```bash
python pf.py --help
python pf.py search --help
```

### A sensible first session

```bash
python pf.py demo
python pf.py check --live
python pf.py search "wax seal kit"
python pf.py compare "wax seal kit" "wax seal stamp" "sealing wax sticks" --brief
```

---

## 7. Reading the output

### The Etsy summary row

| Column | Meaning |
| --- | --- |
| **Competing** | How many active Etsy listings match your keyword. This is your competition. Lower is better. |
| **Sampled** | How many of those the tool actually downloaded (Etsy caps this at 100 per request). |
| **Avg favs** | Average favourites across the sample. Your demand signal. Higher is better. |
| **Top favs** | Favourites on the single most popular listing — proof of what is possible here. |
| **Shops** | How many different shops are in the sample. A low number means a few sellers dominate. |
| **Typical price** | The **median** price of the sample. This is the price the profit maths assumes you could sell at. |
| **Price range** | The 25th to 75th percentile, so you can see how spread out prices are. |
| **Demand** | 0–100 score from favourites. |
| **Low-comp** | 0–100 score, where **high means few competitors**. |

### The flags

- **`LOW COMPETITION + HIGH FAVORITES`** — the combination you are hunting:
  under 2,500 competing listings *and* at least 150 average favourites. Look
  here first. Both numbers are tunable (`LOW_COMPETITION_LISTINGS`,
  `HIGH_FAVORITES_AVERAGE`).
- `low competition` / `high favorites` — one of the two, but not both.
- `saturated` — 10,000+ competing listings. Hard to get seen.
- `dominated by few shops` — a handful of sellers hold the sample. Could mean an
  entrenched brand, or a gap nobody has noticed.
- `low price ceiling` — median under $8, so fees eat most of the margin.

### The AliExpress table

| Column | Meaning |
| --- | --- |
| **Cost** | The AliExpress item price. |
| **Ship** | Shipping to you. **A `~` means it was assumed, not reported** — see the limitations section. |
| **Landed** | Cost + shipping. What the item really costs you. |
| **Orders** | How many have been sold recently. The best single sign of a reliable supplier. |
| **Rate** | Rating out of 5. Nearly everything scores 4.5+, so weigh Orders more heavily. |
| **Supp** | Supplier confidence, 0–100: 65% order volume, 35% rating. |
| **Fees** | What Etsy takes on that sale. |
| **Profit** | Your estimated profit per sale. Green means it clears $3 profit *and* 20% margin. |
| **Margin** | Profit as a percentage of revenue. |

### The saved files

Both land in `reports/` with a timestamp in the filename, so nothing is
overwritten:

- **The CSV** has one row per AliExpress match with *every* intermediate number,
  including each fee separately. Open it in Excel or Google Sheets and redo the
  maths yourself — you should get the same answers.
- **The HTML report** is a single self-contained file. Double-click to open it.
  It works offline, has clickable links to every listing and product, and
  follows your system light/dark setting.

---

## 8. How the numbers are calculated

All of it lives in two small, heavily commented files:
`product_finder/economics.py` and `product_finder/scoring.py`.

### Profit, per sale

```
revenue = your Etsy price + any shipping you charge the buyer
fees    = revenue × 6.5%        (Etsy transaction fee)
        + revenue × 3% + $0.25  (payment processing, US rate)
        + $0.20                 (listing fee)
cost    = AliExpress price + shipping to you
profit  = revenue − fees − cost
margin  = profit ÷ revenue
```

Worked example, taken from a real demo run:

```
Etsy median price      $30.48
AliExpress item         $3.16
Shipping (assumed)      $2.50   →  landed cost $5.66
Transaction fee  6.5%   $1.98
Payment    3% + $0.25   $1.16
Listing fee             $0.20   →  total fees  $3.35
                                   ─────────────────
profit = 30.48 − 3.35 − 5.66  =   $21.47   (70% margin)
```

**Why the median price, not the average?** A few $200 "deluxe bundle" listings
would drag an average far above anything you could realistically charge. The
median follows the middle of the market.

### The scores

Etsy gives us no sales figures. It gives favourites and a listing count, so
those are what we use:

- **Demand score** — from average favourites per listing, plus a smaller
  contribution from the single best listing.
- **Low-competition score** — the total number of competing listings, inverted.
- **Opportunity score** — 55% demand + 45% low-competition. Demand is weighted
  higher because an empty niche nobody wants is worth nothing.
- **Niche score** (used for `compare`) — 50% opportunity + 30% best profit
  (capped at $20) + 20% best margin (capped at 60%). A niche with no profitable
  supplier scores near zero however popular it is.

Each score maps a **range** onto 0–100 on a **logarithmic** curve. The log
matters because these numbers are hugely skewed: going from 10 to 100
competing listings matters far more than going from 9,010 to 9,100. The range
matters too — an earlier version scaled up from zero to a single reference
point, and the result was that *every* real Etsy keyword scored 100 on demand,
which made comparing niches meaningless.

The ranges are set in `.env`, so you can tune them without touching code:

| Setting | Default | Meaning |
| --- | --- | --- |
| `DEMAND_FAVORITES_LOW` | `10` | This many average favourites scores 0 |
| `DEMAND_FAVORITES_HIGH` | `2000` | This many or more scores 100 |
| `COMPETITION_LISTINGS_LOW` | `200` | This few competitors scores 100 |
| `COMPETITION_LISTINGS_HIGH` | `50000` | This many or more scores 0 |

**If everything you search scores 100 on demand, raise
`DEMAND_FAVORITES_HIGH`.** Popular craft-supply keywords routinely average
several hundred favourites per listing, and the scores are only useful if they
spread your actual candidates across the range rather than pinning them at the
top.

**Favourites are a proxy for demand, not a measure of sales.** People favourite
things they want but have not bought. Treat the scores as a way to sort a
shortlist, then go and look at the real listings yourself.

---

## 9. Changing the settings

Everything configurable lives in `.env`, and `.env.example` documents each one.
The ones you are most likely to change:

| Setting | Default | Why change it |
| --- | --- | --- |
| `ETSY_TRANSACTION_RATE` | `0.065` | Etsy changes its fees. Check your own fee page. |
| `ETSY_PAYMENT_RATE` / `_FLAT` | `0.03` / `0.25` | Payment processing differs by country. |
| `ETSY_OFFSITE_ADS_RATE` | `0.0` | Set to `0.15` to see a pessimistic worst case where every sale came via an Etsy ad. |
| `ETSY_SHIPPING_CHARGED` | `0.0` | Set this if you plan to charge for shipping rather than offering it free. |
| `ASSUMED_SHIPPING` | `2.50` | What to assume AliExpress shipping costs when the API does not say. |
| `SHIP_TO_COUNTRY` | `US` | Your country, which changes AliExpress prices. |
| `CACHE_TTL_HOURS` | `24` | How long to reuse saved API responses. |
| `DEMAND_FAVORITES_HIGH` | `2000` | Raise it if every keyword scores 100 on demand. |
| `HIGH_FAVORITES_AVERAGE` | `150` | The bar for the "high favorites" flag. |

Rates are decimals: `0.065` means 6.5%.

See exactly what is in effect with:

```bash
python pf.py check
```

---

## 9b. Running more than one store

The tool is **keyword-agnostic** — nothing in it is specific to craft
supplies. But the scoring thresholds are category-specific, so a second store
needs its own calibration rather than its own copy of the tool.

Use a **profile**: a file called `.env.<name>` holding only what differs for
that store.

```bash
python pf.py compare "linen jumpsuit" "nursing dress" --profile clothing
```

- `.env.clothing` is read **first**, then `.env` fills in everything it did
  not set — so your **API keys stay in `.env` only**. Never copy keys into a
  profile.
- Reports go to `reports/clothing/` automatically, keeping stores apart.
- `--profile` works before or after the subcommand.
- Every `.env.*` file is gitignored, so profiles never reach GitHub.

### Why categories need different numbers

Measured on real searches, clothing is about **ten times more crowded** than
craft supplies:

| Keyword | Competing listings |
| --- | --- |
| wax seal kit (craft) | 10,884 |
| sealing wax sticks (craft) | 1,132 |
| crochet top (apparel) | 137,474 |
| linen dress (apparel) | 118,180 |

With the craft-supply defaults every clothing keyword scored **0** on
competition, so the ranking could not tell them apart at all. The bundled
`.env.clothing` raises `COMPETITION_LISTINGS_HIGH` to 400,000 and the
saturation flag to 80,000, which spreads apparel keywords across the range
again.

**The lesson generalises.** When you start a new category, run three or four
keywords you already know are big, see where they land, and move the
thresholds until the scores spread out. If everything scores 100 or everything
scores 0, the dial is wrong, not the niche.

## 10. The cache

Every API response is saved as a JSON file in `.cache/`. Run the same search
again within 24 hours and it is read from disk instead of called again. This
keeps you comfortably inside both APIs' rate limits and makes repeat runs
instant.

```bash
python pf.py cache           # how much is cached
python pf.py cache --clear   # empty it
python pf.py search "x" --refresh    # fetch fresh, overwrite the cache
python pf.py search "x" --no-cache   # neither read nor write the cache
```

---

## 11. Troubleshooting

**`python: command not found`**
Python is not installed or not on your PATH. Try `python3` instead, or
reinstall from python.org with "Add Python to PATH" ticked.

**`Configuration problem: ETSY_API_KEY is missing`**
You have not made your `.env` yet, or it is in the wrong folder. It must sit
next to `pf.py`. Check with `ls` (macOS/Linux) or `dir` (Windows) — note that
`ls` hides dotfiles, so use `ls -a`.

**`HTTP 403` from Etsy, mentioning `keystring:shared_secret`**
This is the most common error. You have set `ETSY_API_KEY` but not
`ETSY_SHARED_SECRET`. Etsy needs both. Get the secret from
[etsy.com/developers/your-apps](https://www.etsy.com/developers/your-apps) by
clicking the **eye / visibility icon**, and add it to `.env`.
Confirm with `python pf.py check`.

**`HTTP 403` from Etsy for any other reason**
Your app is probably **not approved yet**. Etsy's docs: *"Your API key is not
active until it has been approved."* Check the status under *Manage Your Apps*.

**`HTTP 401` from Etsy**
A credential was rejected. Re-copy both values, with no spaces and no quotes,
and confirm your app is approved.

**`HTTP 429` — rate limited**
You are calling too often. Etsy enforces both a per-second (QPS) and a
per-day (QPD) limit at the API-key level, and returns a `retry-after` header.
The tool honours that header and retries automatically, but you can also just
wait. **Your app's actual limits are shown in the Developer Portal** at
[etsy.com/developers/your-apps](https://www.etsy.com/developers/your-apps) —
Etsy does not publish a universal number. The daily quota is a rolling
24-hour window, not a midnight reset, so it frees up gradually. The cache
exists to keep you well clear of all this.

**AliExpress: `Invalid signature` / `IncompleteSignature`**
Almost always one of three things:
1. `ALIEXPRESS_APP_SECRET` is wrong or has a stray space. Re-copy it.
2. **Your computer's clock is wrong.** Signed requests include a timestamp and
   are rejected if it drifts too far. Turn on automatic time syncing.
3. Your app is on the legacy signing scheme. Set
   `ALIEXPRESS_SIGN_METHOD=md5` in `.env` and try again.

**AliExpress: a `resp_code` error, or no products**
Usually means your app is not approved for `aliexpress.affiliate.product.query`
yet. Check your app's permissions in the Open Platform console. Meanwhile,
`--etsy-only` still gives you useful demand research.

**Etsy returns no listings**
Try a broader keyword. `"wax seal"` finds far more than
`"vintage brass wax seal stamp kit"`.

**Garbled characters in the terminal**
Run `chcp 65001` in PowerShell before the tool to switch the console to UTF-8.

**I want to see what is actually being sent**
The cache files in `.cache/` are the raw, unmodified API responses, saved as
readable JSON. Open one in a text editor — it is the best way to learn what
these APIs really return.

---

## 12. How the code is organised

Each file does one job, and all of them are commented for a beginner. Read
them in roughly this order:

```
pf.py                    The entry point you run. Four lines of real work.
product_finder/
  config.py              Reads .env, holds the fee settings. Start here.
  http.py                The only file that talks to the internet.
  etsy.py                Etsy Open API v3 client. Fetch + flatten listings.
  aliexpress.py          AliExpress client, including request signing.
  economics.py           The profit maths. Pure arithmetic, no API calls.
  scoring.py             Demand, competition and niche scoring.
  analysis.py            Orchestrates one keyword end to end.
  report.py              Writes the CSV and the HTML report.
  table.py               Terminal tables and colour.
  cache.py               The on-disk cache.
  cli.py                 Argument parsing and all terminal output.
  demo.py                Sample data for `pf.py demo`.
```

A good first change: edit `HIGH_FAVORITES_AVERAGE` or
`DEMAND_FAVORITES_HIGH` in your `.env`, then re-run `python pf.py demo` and
watch the scores and flags move. No code change needed.

---

## 13. Honest limitations — please read

This tool makes **estimates from public data**. It is a way to narrow a long
list of ideas down to a few worth investigating properly. It is not a
prediction of what will sell, and the following gaps are real:

**On the demand side**
- **Favourites are not sales.** Etsy's public API does not expose sales
  figures. Favourites measure interest, which correlates with demand but is
  not the same thing.
- **The sample is capped at ~100 listings** per keyword, which Etsy sorts by
  its own relevance score. A keyword with 20,000 listings is judged on the
  first 100.
- **There is no trend or seasonality data.** A score is a snapshot of today.
  Run the same keyword monthly and compare if you want a trend.

**On the cost side**
- **Shipping is often assumed, not known.** The AliExpress affiliate endpoint
  usually does not return a shipping price — that lives behind separate
  freight APIs that need extra permissions. Rows marked `~` use your
  `ASSUMED_SHIPPING` value. **Always check real shipping on the product page
  before committing to anything.**
- **Prices move.** AliExpress prices change constantly and vary by destination
  country and quantity. Cached data can be up to 24 hours old.
- **Keyword matching is naive.** The tool trusts both search engines. The
  cheapest "wax seal kit" on AliExpress may be a 3-piece set while the Etsy
  listings are 40-piece kits. **Compare what is actually in the box yourself.**

**On the money**
- **Excluded from the maths:** sales tax and VAT, import duty, currency
  conversion spreads, Etsy Ads and Offsite Ads (unless you enable the rate),
  returns, breakage, lost parcels, packaging, and your own time.
- **Fees change and vary by country.** The defaults are the standard US
  schedule at the time of writing. Check your own Etsy fee page and update
  `.env`.

**On the business itself**
- **Plain reselling is against Etsy's rules.** Etsy is a handmade,
  vintage and craft-supply marketplace. Commercial craft *supplies* are an
  allowed category, but listing a mass-produced item as your own handmade work
  is not, and shops get closed for it. Read Etsy's Handmade Policy and Seller
  Policy, and be clear in your listings about what you made and what you
  sourced.
- **Long shipping times from AliExpress** cause the cancellations and bad
  reviews that sink new shops. Factor that in.
- **Nothing here is business or financial advice.** Verify every number
  yourself before spending money.

---

## Licence and credit

Yours to use and change freely. Built with Python's standard library only.

Data sources: the [Etsy Open API v3](https://developers.etsy.com/documentation/)
and the [AliExpress Open Platform](https://openservice.aliexpress.com).
Respect both platforms' terms of service and rate limits.
