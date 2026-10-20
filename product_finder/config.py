"""Settings loading.

Two jobs:

1. Read secrets (API keys) out of a `.env` file so they never live in the code.
2. Hold the fee numbers used for the profit maths, with sensible defaults
   you can override in `.env`.

We deliberately use only Python's standard library, so there is nothing to
`pip install` -- the tiny `.env` parser below replaces `python-dotenv`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Where we look for the .env file: the project folder (one level up from this
# file). You can point somewhere else with the PRODUCT_FINDER_ENV variable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


class SettingsError(RuntimeError):
    """Raised when settings are missing or malformed, with a readable message."""


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read a `.env` file into os.environ (without overwriting real env vars).

    Supported syntax, which is all you need:

        # a comment
        KEY=value
        KEY="value with spaces"
        export KEY=value
    """
    env_path = path or Path(os.environ.get("PRODUCT_FINDER_ENV", DEFAULT_ENV_PATH))
    found: dict[str, str] = {}
    if not env_path.is_file():
        return found

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if value[:1] in ("\"", "'") and value.find(value[0], 1) != -1:
            # Quoted: take what is inside the first matching pair of quotes,
            # and ignore anything after the closing quote. This is how you
            # keep a '#' or a trailing comment off a value.
            quote = value[0]
            value = value[1 : value.find(quote, 1)]
        else:
            # Unquoted: a '#' that follows whitespace starts a trailing
            # comment, so that `ETSY_LIMIT=100   # max 100` reads as "100".
            # A '#' with no space before it is kept, since it may be part of
            # the value itself (a colour code, say).
            for marker in (" #", "\t#"):
                position = value.find(marker)
                if position != -1:
                    value = value[:position]
            value = value.strip()

        if not key:
            continue
        found[key] = value
        # A real environment variable always wins over the file, which lets you
        # override a single key for one run without editing .env.
        os.environ.setdefault(key, value)
    return found


def _env_float(name: str, default: float) -> float:
    """Read a number from the environment, falling back to `default`."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise SettingsError(
            f"{name} in your .env is {raw!r}, which is not a number."
        ) from None


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


def _is_placeholder(value: str) -> bool:
    """True if this is still the example text, not a real credential.

    Copying .env.example to .env leaves lines like

        ETSY_API_KEY=paste_your_etsy_keystring_here

    Treating those as real would send gibberish to the API and produce a
    confusing 403. We treat them as missing instead, so you get the clear
    'key is missing' message that tells you what to do.
    """
    lowered = value.strip().lower()
    return lowered.startswith("paste_your") or lowered.endswith("_here")


def _credential(name: str) -> str:
    """Read a secret from the environment, ignoring unedited placeholders."""
    value = os.environ.get(name, "").strip()
    return "" if _is_placeholder(value) else value


@dataclass
class Fees:
    """Etsy's selling costs, as fractions and flat dollar amounts.

    Defaults match Etsy's standard US fee schedule at the time of writing:
      - 6.5% transaction fee on the item price
      - 3% + $0.25 payment processing (US rate)
      - $0.20 to publish a listing

    All of these are configurable because Etsy changes them, they differ by
    country, and extras like Offsite Ads or Etsy Plus are not included here.
    Always check your own Etsy fee page before trusting the numbers.
    """

    transaction_rate: float = 0.065
    payment_rate: float = 0.03
    payment_flat: float = 0.25
    listing_flat: float = 0.20
    # Optional extra, off by default: Etsy's Offsite Ads cut (12% or 15%)
    # applies only to orders that come from an Etsy-bought ad.
    offsite_ads_rate: float = 0.0
    # What you expect to charge the buyer for shipping (0 = free shipping,
    # which is what most Etsy sellers do, so the cost comes out of your margin).
    shipping_charged: float = 0.0

    @classmethod
    def from_env(cls) -> "Fees":
        return cls(
            transaction_rate=_env_float("ETSY_TRANSACTION_RATE", 0.065),
            payment_rate=_env_float("ETSY_PAYMENT_RATE", 0.03),
            payment_flat=_env_float("ETSY_PAYMENT_FLAT", 0.25),
            listing_flat=_env_float("ETSY_LISTING_FEE", 0.20),
            offsite_ads_rate=_env_float("ETSY_OFFSITE_ADS_RATE", 0.0),
            shipping_charged=_env_float("ETSY_SHIPPING_CHARGED", 0.0),
        )


@dataclass
class Thresholds:
    """The dials that turn raw Etsy numbers into 0-100 scores.

    These are judgement calls, not facts, and the right values depend on your
    category. The defaults were calibrated against real craft-supply searches,
    where a popular keyword averages hundreds of favourites per listing -- far
    more than you might guess.

    Each score maps a *range* onto 0-100 on a log curve: at or below `low` you
    score 0, at or above `high` you score 100. Using a range rather than
    counting up from zero is what stops every busy keyword scoring 100.
    """

    # Average favourites per listing: this many or fewer scores 0 on demand...
    demand_favorites_low: float = 10.0
    # ...and this many or more scores 100.
    demand_favorites_high: float = 2000.0

    # Competing listings: this many or fewer scores 100 on low-competition...
    competition_listings_low: float = 200.0
    # ...and this many or more scores 0.
    competition_listings_high: float = 50000.0

    # Flag thresholds.
    low_competition_listings: int = 2500
    high_favorites_average: float = 150.0
    saturated_listings: int = 10000
    # If the biggest Etsy category holds less than this percentage of the
    # sampled listings, the keyword spans product types and gets flagged.
    mixed_category_share: float = 45.0

    @classmethod
    def from_env(cls) -> "Thresholds":
        return cls(
            demand_favorites_low=_env_float("DEMAND_FAVORITES_LOW", 10.0),
            demand_favorites_high=_env_float("DEMAND_FAVORITES_HIGH", 2000.0),
            competition_listings_low=_env_float("COMPETITION_LISTINGS_LOW", 200.0),
            competition_listings_high=_env_float("COMPETITION_LISTINGS_HIGH", 50000.0),
            low_competition_listings=_env_int("LOW_COMPETITION_LISTINGS", 2500),
            high_favorites_average=_env_float("HIGH_FAVORITES_AVERAGE", 150.0),
            saturated_listings=_env_int("SATURATED_LISTINGS", 10000),
            mixed_category_share=_env_float("MIXED_CATEGORY_SHARE", 45.0),
        )


@dataclass
class Settings:
    """Everything the tool needs to run."""

    etsy_api_key: str = ""
    etsy_shared_secret: str = ""
    aliexpress_app_key: str = ""
    aliexpress_app_secret: str = ""
    aliexpress_tracking_id: str = ""

    # API behaviour
    etsy_limit: int = 100
    aliexpress_limit: int = 40
    currency: str = "USD"
    ship_to_country: str = "US"
    aliexpress_gateway: str = "https://api-sg.aliexpress.com/sync"
    aliexpress_sign_method: str = "sha256"

    # When AliExpress does not report a shipping price (common on the
    # affiliate endpoint), assume this many dollars so the profit maths still
    # produces a usable -- clearly flagged -- estimate.
    assumed_shipping: float = 2.50

    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / ".cache")
    cache_ttl_hours: float = 24.0
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "reports")

    fees: Fees = field(default_factory=Fees)
    thresholds: "Thresholds" = field(default_factory=lambda: Thresholds())

    @classmethod
    def load(
        cls, env_path: Path | None = None, profile: str | None = None
    ) -> "Settings":
        """Load settings, optionally layering a per-store profile on top.

        A profile is a file like `.env.clothing` holding only what differs for
        that store -- its scoring calibration, its fee rates, its own reports
        folder. Shared things, above all your API keys, stay in `.env` so they
        live in exactly one place.

        The profile is read FIRST and the base `.env` second. `load_env` uses
        `setdefault`, so whatever the profile set stays put and the base only
        fills the gaps. That is what makes the profile win.
        """
        if profile:
            profile_path = PROJECT_ROOT / f".env.{profile}"
            if not profile_path.is_file():
                raise SettingsError(
                    f"No profile file at {profile_path.name}.\n"
                    f"  Create it with the settings specific to that store, e.g.\n"
                    f"    OUTPUT_DIR=reports/{profile}\n"
                    f"    COMPETITION_LISTINGS_HIGH=400000\n"
                    f"  Keep your API keys in .env -- profiles inherit from it."
                )
            load_env(profile_path)

        load_env(env_path)

        # Unless the profile said otherwise, keep each store's reports apart so
        # one store's CSVs do not pile up in another's folder.
        if profile and not os.environ.get("OUTPUT_DIR"):
            os.environ["OUTPUT_DIR"] = str(PROJECT_ROOT / "reports" / profile)

        return cls(
            etsy_api_key=_credential("ETSY_API_KEY"),
            etsy_shared_secret=_credential("ETSY_SHARED_SECRET"),
            aliexpress_app_key=_credential("ALIEXPRESS_APP_KEY"),
            aliexpress_app_secret=_credential("ALIEXPRESS_APP_SECRET"),
            aliexpress_tracking_id=_credential("ALIEXPRESS_TRACKING_ID"),
            etsy_limit=max(1, min(100, _env_int("ETSY_LIMIT", 100))),
            aliexpress_limit=max(1, min(50, _env_int("ALIEXPRESS_LIMIT", 40))),
            currency=os.environ.get("CURRENCY", "USD").strip().upper() or "USD",
            ship_to_country=os.environ.get("SHIP_TO_COUNTRY", "US").strip().upper()
            or "US",
            aliexpress_gateway=os.environ.get(
                "ALIEXPRESS_GATEWAY", "https://api-sg.aliexpress.com/sync"
            ).strip(),
            aliexpress_sign_method=os.environ.get("ALIEXPRESS_SIGN_METHOD", "sha256")
            .strip()
            .lower(),
            assumed_shipping=_env_float("ASSUMED_SHIPPING", 2.50),
            cache_dir=Path(os.environ.get("CACHE_DIR", str(PROJECT_ROOT / ".cache"))),
            cache_ttl_hours=_env_float("CACHE_TTL_HOURS", 24.0),
            output_dir=Path(os.environ.get("OUTPUT_DIR", str(PROJECT_ROOT / "reports"))),
            fees=Fees.from_env(),
            thresholds=Thresholds.from_env(),
        )

    @property
    def etsy_auth(self) -> str:
        """The exact value for Etsy's `x-api-key` header.

        Etsy wants BOTH credentials, colon-joined:

            x-api-key: <keystring>:<shared_secret>

        We accept either style of configuration: the two values in separate
        variables, or the already-joined string pasted into ETSY_API_KEY.
        """
        if ":" in self.etsy_api_key:
            return self.etsy_api_key  # already joined by the user
        if self.etsy_shared_secret:
            return f"{self.etsy_api_key}:{self.etsy_shared_secret}"
        return self.etsy_api_key  # will be rejected; require_etsy explains why

    def require_etsy(self) -> None:
        if not self.etsy_api_key:
            raise SettingsError(
                "ETSY_API_KEY is missing.\n"
                "  1. Copy .env.example to .env\n"
                "  2. Paste your Etsy keystring into ETSY_API_KEY\n"
                "  3. Paste your shared secret into ETSY_SHARED_SECRET\n"
                "  See the README section 'Step 2: Get your Etsy API key'."
            )
        if ":" not in self.etsy_api_key and not self.etsy_shared_secret:
            raise SettingsError(
                "ETSY_SHARED_SECRET is missing.\n"
                "  Etsy needs BOTH of your app's credentials, sent as\n"
                "  'keystring:shared_secret'. Find them together at\n"
                "  https://www.etsy.com/developers/your-apps -- click the\n"
                "  visibility (eye) icon to reveal the shared secret.\n"
                "  Then set ETSY_SHARED_SECRET in your .env."
            )

    def require_aliexpress(self) -> None:
        missing = [
            name
            for name, value in (
                ("ALIEXPRESS_APP_KEY", self.aliexpress_app_key),
                ("ALIEXPRESS_APP_SECRET", self.aliexpress_app_secret),
            )
            if not value
        ]
        if missing:
            raise SettingsError(
                f"Missing in your .env: {', '.join(missing)}.\n"
                "  See the README section 'Step 3: Get your AliExpress API keys'."
            )
