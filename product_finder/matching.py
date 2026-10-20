"""Judging whether an AliExpress product is actually the thing Etsy is selling.

The problem this solves:

We find your Etsy market by keyword, then search AliExpress with the same
keyword. But a keyword match is not a product match. Search AliExpress for
"wax seal kit" and you get 3-piece sets, 40-piece sets, loose wax beads and
spare brass heads -- all legitimately "wax seal kit", none of them necessarily
the thing whose price you measured on Etsy. Ranking those purely by profit
puts the *least comparable* item first, because the cheapest listing is
usually the smallest one.

So we build a picture of what the Etsy market is actually selling, from the
words its best-performing listings use, and score each AliExpress product
against it. That does not make the match certain -- only your eyes on the
product page can -- but it reliably sinks the obvious mismatches.

This is all local text analysis. No extra API calls, no model, no network.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .etsy import EtsyListing

# Words that carry no signal about what a product *is*. Mostly marketplace
# filler: both sites' titles are stuffed with it for search reasons.
STOPWORDS = frozenset("""
a an and or the of for with to in on at by from is are be this that these those
new hot sale free shipping gift gifts best top quality high premium set sets
pcs pc piece pieces pack packs lot bulk wholesale diy custom customized personalized
handmade handcrafted vintage retro style styles fashion fashionable trendy
women womens woman ladies lady girls girl mens men man unisex adult adults
size sizes small medium large xl xxl plus mini maxi
color colors colour colours multicolor assorted various different
item items product products accessory accessories supply supplies tool tools
kit kits
""".split())

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenise(text: str) -> list[str]:
    """Lower-case words, minus stopwords and one-character noise."""
    return [
        token
        for token in _TOKEN.findall(str(text).lower())
        if len(token) > 2 and token not in STOPWORDS
    ]


def market_vocabulary(
    listings: list[EtsyListing], limit: int = 60
) -> dict[str, float]:
    """What this Etsy market is made of, as weighted words.

    Titles are weighted by favourites, so the vocabulary reflects what
    *sells* rather than what merely exists. A word in a 5,000-favourite
    listing says more about the market than the same word in a listing nobody
    has looked at.

    Weights are normalised so the commonest word scores 1.0.
    """
    if not listings:
        return {}

    scores: Counter[str] = Counter()
    for item in listings:
        # log1p keeps one runaway listing from drowning out everything else,
        # while still letting popularity count. The +1 floor means listings
        # with no favourites still contribute a little.
        weight = 1.0 + math.log1p(max(0, item.num_favorers))
        seen = set(tokenise(item.title))
        # Tags are curated by the seller and are often cleaner than titles.
        seen.update(tokenise(" ".join(item.tags)))
        for token in seen:
            scores[token] += weight

    if not scores:
        return {}
    top = scores.most_common(limit)
    highest = top[0][1] or 1.0
    return {token: round(weight / highest, 4) for token, weight in top}


#. How many of the market's most important words define "the same product".
CORE_TERMS = 10


def match_score(title: str, vocabulary: dict[str, float]) -> float:
    """0-100: how much this product title looks like the Etsy market.

    Scored as weighted recall of the market's CORE terms -- the handful of
    words that actually say what the product is -- rather than overlap with
    the whole vocabulary.

    That distinction matters. Measured against the long tail, a paint brush
    scored "similar" to a wax seal kit purely for sharing the word "wooden",
    because one incidental hit is a meaningful slice of a 60-word vocabulary.
    Against the core terms it scores 11, which is the right answer.

    Known blind spot: this reads words, not meaning, so "no stamp included"
    counts as a hit on "stamp". Treat the score as a sorting aid, never as
    confirmation -- the product page is the only real check.
    """
    if not vocabulary:
        return 0.0
    tokens = set(tokenise(title))
    if not tokens:
        return 0.0

    core = list(vocabulary.items())[:CORE_TERMS]
    total = sum(weight for _, weight in core) or 1.0
    hit = sum(weight for token, weight in core if token in tokens)
    return round(min(100.0, 100.0 * hit / total), 1)


def describe_match(score: float) -> str:
    """A plain-language reading, so the number is not just a number."""
    if score >= 55:
        return "close match"
    if score >= 35:
        return "similar"
    if score >= 20:
        return "loose"
    return "probably different"
