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
        # Strip one matching pair of surrounding quotes, if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
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

    @classmethod
    def load(cls, env_path: Path | None = None) -> "Settings":
        load_env(env_path)
        return cls(
            etsy_api_key=os.environ.get("ETSY_API_KEY", "").strip(),
            etsy_shared_secret=os.environ.get("ETSY_SHARED_SECRET", "").strip(),
            aliexpress_app_key=os.environ.get("ALIEXPRESS_APP_KEY", "").strip(),
            aliexpress_app_secret=os.environ.get("ALIEXPRESS_APP_SECRET", "").strip(),
            aliexpress_tracking_id=os.environ.get("ALIEXPRESS_TRACKING_ID", "").strip(),
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
