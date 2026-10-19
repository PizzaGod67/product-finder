"""The one place we talk to the internet.

Normally you would reach for the `requests` library here. We use the standard
library's `urllib` instead so that this project needs zero installs. The
behaviour you actually want from `requests` -- JSON decoding, timeouts, and
retrying on a rate limit -- is written out below.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "product-finder/1.0 (+https://example.invalid/product-finder)"


class ApiError(RuntimeError):
    """An API call failed in a way worth showing the user."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _decode(raw: bytes, url: str) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ApiError(
            f"{url} did not return JSON. First 200 characters:\n{text[:200]}"
        ) from None


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> Any:
    """Make an HTTP request and return the decoded JSON body.

    Retries on 429 (too many requests) and 5xx server errors, waiting a little
    longer each time. Raises ApiError with a readable message otherwise.
    """
    if params:
        # Drop empty values so we never send `&tracking_id=`.
        clean = {k: str(v) for k, v in params.items() if v not in (None, "")}
        url = f"{url}?{urllib.parse.urlencode(clean)}"

    body: bytes | None = None
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        all_headers.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(
            {k: str(v) for k, v in data.items() if v not in (None, "")}
        ).encode("utf-8")
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"

    last_error: ApiError | None = None
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url, data=body, headers=all_headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return _decode(response.read(), url)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            last_error = ApiError(
                _explain_status(exc.code, detail), status=exc.code, body=detail
            )
            if not retryable or attempt == max_retries:
                raise last_error from None
            # Honour Retry-After when the server sends it.
            wait = exc.headers.get("Retry-After")
            delay = float(wait) if (wait or "").isdigit() else 2.0 * attempt
            time.sleep(min(delay, 30.0))
        except urllib.error.URLError as exc:
            last_error = ApiError(
                f"Could not reach {urllib.parse.urlsplit(url).netloc}: {exc.reason}. "
                "Check your internet connection."
            )
            if attempt == max_retries:
                raise last_error from None
            time.sleep(1.5 * attempt)
        except TimeoutError:
            last_error = ApiError(f"Request to {url} timed out after {timeout:.0f}s.")
            if attempt == max_retries:
                raise last_error from None

    raise last_error or ApiError("Request failed for an unknown reason.")


def _explain_status(code: int, detail: str) -> str:
    """Turn an HTTP status code into something a beginner can act on."""
    snippet = detail.strip()[:300]
    hints = {
        400: "The API rejected the request as malformed (check your keyword/params).",
        401: "Your API key was rejected. Check ETSY_API_KEY / your AliExpress keys in .env.",
        403: (
            "Access denied. Read the API's own message below -- for Etsy it is\n"
            "  usually one of:\n"
            "    'should be in the format keystring:shared_secret'\n"
            "        -> ETSY_SHARED_SECRET is missing from your .env\n"
            "    'not found or not active, or incorrect shared secret'\n"
            "        -> a credential is wrong, OR your app is not approved yet\n"
            "           (keys stay inactive until Etsy approves the app)\n"
            "  Both values are at https://www.etsy.com/developers/your-apps"
        ),
        404: "That endpoint does not exist (check the URL in your .env, if you changed it).",
        429: "Rate limited -- too many requests. Wait a bit, or rely on the cache.",
        500: "The API had an internal error. Not your fault; try again shortly.",
        503: "The API is temporarily unavailable. Try again shortly.",
    }
    hint = hints.get(code, "Unexpected response from the API.")
    return f"HTTP {code}: {hint}" + (f"\nAPI said: {snippet}" if snippet else "")
