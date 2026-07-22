import csv
import math
import os
import re
import smtplib
import requests
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Iterable

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


SITES = [
    {
        "name": "AWS Machine Learning Engineer Nanodegree",
        "url": "https://www.udacity.com/course/aws-machine-learning-engineer-nanodegree--nd189",
    },
    {
        "name": "AI for Business Leaders Nanodegree",
        "url": "https://www.udacity.com/course/ai-for-business-leaders--nd054",
    },
]

HISTORY_PATH = Path(os.getenv("HISTORY_PATH", "data/udacity_prices.csv"))
ALERTS_PATH = Path(os.getenv("ALERTS_PATH", "data/udacity_alerts.csv"))

MIN_HISTORY_POINTS = int(os.getenv("MIN_HISTORY_POINTS", "5"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))
DROP_PCT_THRESHOLD = float(os.getenv("DROP_PCT_THRESHOLD", "0.25"))
Z_SCORE_THRESHOLD = float(os.getenv("Z_SCORE_THRESHOLD", "1.25"))
MIN_VALID_PRICE = float(os.getenv("MIN_VALID_PRICE", "50"))
ALERT_COOLDOWN_DAYS = int(os.getenv("ALERT_COOLDOWN_DAYS", "7"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class PriceCandidate:
    currency: str
    amount: float
    raw: str
    context: str


@dataclass
class PriceSnapshot:
    timestamp_utc: str
    name: str
    url: str
    currency: str
    price: float
    original_price: float | None
    discount_amount: float | None
    discount_percent: float | None
    raw: str
    context: str


@dataclass
class Alert:
    snapshot: PriceSnapshot
    historical_median: float
    historical_mean: float
    historical_min: float
    historical_count: int
    reason: str


@dataclass
class PriceSelection:
    current: PriceCandidate
    original: PriceCandidate | None
    discount_amount: float | None
    discount_percent: float | None
    source: str


def main() -> int:
    generated_alerts: list[Alert] = []
    errors: list[str] = []
    successful_snapshots = 0

    for site in SITES:
        print(f"[check] Getting price for: {site['name']}")

        try:
            snapshot = get_price(site)
            history = load_history(snapshot.url, snapshot.currency)
            append_snapshot(snapshot)
            successful_snapshots += 1
            print(
                f"[price] {snapshot.name}: "
                f"{snapshot.currency} {snapshot.price:.2f}"
            )
            alert = build_alert(snapshot, history)

            if alert is None:
                continue

            if alert_recently_sent(alert):
                print(
                    f"[skip] Alert already sent for {snapshot.name} at this price. Skipping to avoid spamming."
                )
                continue

            generated_alerts.append(alert)

        except Exception as exc:
            message = f"{site['name']}: {exc}"
            errors.append(message)
            print(f"[error] {message}", file=sys.stderr)

    email_sent = send_email(generated_alerts)

    if email_sent:
        for alert in generated_alerts:
            append_alert(alert)

    print("")
    print("Summary:")
    print(f"- Pages processed successfully: {successful_snapshots}")
    print(f"- Alerts generated: {len(generated_alerts)}")
    print(f"- EEmail sent: {'yes' if email_sent else 'no'}")

    if errors:
        print("- Errors:")
        for error in errors:
            print(f"  - {error}")

    return 0 if successful_snapshots > 0 else 1


def get_price(site: dict) -> PriceSnapshot:
    text, telemetry = get_page_text(site["url"])
    candidates = extract_prices(text)
    selected = choose_relevant_price(candidates)

    print(
        f"[telemetry] {site['name']}: source={selected.source}; "
        f"candidates={len(candidates)}; details={telemetry}"
    )

    return PriceSnapshot(
        timestamp_utc=now_utc().isoformat(timespec="seconds"),
        name=site["name"],
        url=site["url"],
        currency=selected.current.currency,
        price=round(selected.current.amount, 2),
        original_price=round(selected.original.amount, 2) if selected.original else None,
        discount_amount=round(selected.discount_amount, 2) if selected.discount_amount is not None else None,
        discount_percent=round(selected.discount_percent, 2) if selected.discount_percent is not None else None,
        raw=selected.current.raw,
        context=selected.current.context,
    )


def get_page_text(url: str) -> tuple[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    selectors = [
        "[data-testid*='price']",
        "[class*='price']",
        "[class*='discount']",
        "[id*='price']",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1200},
            locale="en-US",
            extra_http_headers=headers,
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_load_state("networkidle", timeout=30_000)

            for label in ["Accept", "Accept All", "I agree", "Agree", "Got it"]:
                try:
                    page.get_by_role(
                        "button",
                        name=re.compile(label, re.I)
                    ).click(timeout=1_000)
                    break
                except Exception:
                    pass

            page.wait_for_function(
                "document?.body?.innerText && /(?:R\\$|BRL|US\\$|USD|\\$)\\s*\\d/.test(document.body.innerText)",
                timeout=15_000,
            )

            snippets: list[str] = []
            matched_selectors: list[str] = []
            for selector in selectors:
                try:
                    texts = page.locator(selector).all_inner_texts()
                except Exception:
                    continue
                priced_texts = [text for text in texts if re.search(r"(R\$|BRL|US\$|USD|\$)\s*\d", text)]
                if priced_texts:
                    matched_selectors.append(selector)
                    snippets.extend(priced_texts[:4])

            text = page.locator("body").inner_text(timeout=15_000)
            combined = "\n".join(snippets + [text]) if snippets else text
            return combined, ",".join(matched_selectors) if matched_selectors else "body"

        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"Timeout ao abrir a página: {url}") from exc
        finally:
            context.close()
            browser.close()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def extract_prices(text: str) -> list[PriceCandidate]:
    """
    Extract monetary price candidates from the given text, looking for patterns like:
    - R$ 399,00
    - BRL 399.00
    - US$ 1,299.00
    - USD 1.299,00
    - $ 399

    The function normalizes the amounts to float values and filters out candidates 
    below a minimum valid price threshold.
    It also captures some context around the price for later analysis.
    """
    price_pattern = re.compile(
        r"(?P<currency>R\$|BRL|US\$|USD|\$)\s*"
        r"(?P<amount>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)",
        flags=re.IGNORECASE,
    )

    candidates: list[PriceCandidate] = []

    for match in price_pattern.finditer(text):
        currency = match.group("currency").upper()
        amount_raw = match.group("amount")
        raw = match.group(0)

        try:
            amount = normalize_amount(amount_raw)
        except ValueError:
            continue

        if amount < MIN_VALID_PRICE:
            continue

        start = max(0, match.start() - 90)
        end = min(len(text), match.end() + 90)
        context = " ".join(text[start:end].split())

        candidates.append(
            PriceCandidate(
                currency=currency,
                amount=amount,
                raw=raw,
                context=context,
            )
        )

    return deduplicate_prices(candidates)


def normalize_amount(value: str) -> float:
    """
    Normalize values like:
    - 399
    - 399.00
    - 399,00
    - 1,299.00
    - 1.299,00
    """
    value = value.strip()

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            # brazilian format: 1.299,00
            value = value.replace(".", "").replace(",", ".")
        else:
            # american format: 1,299.00
            value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        if len(parts[-1]) == 2:
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    else:
        # could be 399.00 or 1.299.00, but we assume the latter is
        # less common and likely a misformat, so we remove all dots.
        parts = value.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3:
            value = value.replace(".", "")

    return float(value)


def deduplicate_prices(candidates: Iterable[PriceCandidate]) -> list[PriceCandidate]:
    """
    Remove duplicate price candidates that have the same currency and amount (after rounding).
    """
    seen = set()
    unique: list[PriceCandidate] = []

    for candidate in candidates:
        key = (candidate.currency, round(candidate.amount, 2))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    return unique


def choose_relevant_price(candidates: list[PriceCandidate]) -> PriceSelection:
    """
    Given a list of price candidates, choose the most relevant one.
    The heuristic is to select the lowest price,
    as it is more likely to represent the actual cost of the course,
    while higher prices might be promotional or non-standard offers.
    """
    if not candidates:
        raise ValueError("No price candidates found on the page.")

    discount_keywords = re.compile(
        r"\b(discount|save|off|promo|promotion|sale|deal|now|today|was|before|de|por)\b",
        flags=re.IGNORECASE,
    )
    original_keywords = re.compile(
        r"\b(original|list|regular|before|was|old|de)\b",
        flags=re.IGNORECASE,
    )

    current = min(candidates, key=lambda item: item.amount)
    original_candidates = [
        candidate
        for candidate in candidates
        if candidate.amount > current.amount and original_keywords.search(candidate.context)
    ]
    fallback_original_candidates = [candidate for candidate in candidates if candidate.amount > current.amount]
    original = max(original_candidates, key=lambda item: item.amount) if original_candidates else None
    source = "lowest_price"

    if original is None and fallback_original_candidates:
        hinted_current = [item for item in candidates if discount_keywords.search(item.context)]
        if hinted_current:
            current = min(hinted_current, key=lambda item: item.amount)
            fallback_original_candidates = [
                candidate for candidate in candidates if candidate.amount > current.amount
            ]
            if fallback_original_candidates:
                original = max(fallback_original_candidates, key=lambda item: item.amount)
                source = "discount_context"

    discount_amount = None
    discount_percent = None
    if original is not None and original.amount > current.amount:
        discount_amount = original.amount - current.amount
        discount_percent = (discount_amount / original.amount) * 100
        if source == "lowest_price":
            source = "current_and_original"

    return PriceSelection(
        current=current,
        original=original,
        discount_amount=discount_amount,
        discount_percent=discount_percent,
        source=source,
    )


def load_history(url: str, currency: str) -> list[float]:
    if not HISTORY_PATH.exists():
        return []

    cutoff = now_utc() - timedelta(days=LOOKBACK_DAYS)
    prices: list[float] = []

    with HISTORY_PATH.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row.get("url") != url:
                continue

            if row.get("currency") != currency:
                continue

            try:
                timestamp = datetime.fromisoformat(row["timestamp_utc"])
                price = float(row["price"])
            except Exception:
                continue

            if timestamp >= cutoff:
                prices.append(price)

    return prices


def append_snapshot(snapshot: PriceSnapshot) -> None:
    """
    Append a new price snapshot to the history CSV file.
    If the file doesn't exist, it will be created with the appropriate header.
    """
    fieldnames = [
        "timestamp_utc",
        "name",
        "url",
        "currency",
        "price",
        "original_price",
        "discount_amount",
        "discount_percent",
        "raw",
        "context",
    ]

    ensure_csv(HISTORY_PATH, fieldnames)

    with HISTORY_PATH.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writerow(
            {
                "timestamp_utc": snapshot.timestamp_utc,
                "name": snapshot.name,
                "url": snapshot.url,
                "currency": snapshot.currency,
                "price": f"{snapshot.price:.2f}",
                "original_price": f"{snapshot.original_price:.2f}" if snapshot.original_price is not None else "",
                "discount_amount": f"{snapshot.discount_amount:.2f}" if snapshot.discount_amount is not None else "",
                "discount_percent": f"{snapshot.discount_percent:.2f}" if snapshot.discount_percent is not None else "",
                "raw": snapshot.raw,
                "context": snapshot.context,
            }
        )


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()


def build_alert(snapshot: PriceSnapshot, history: list[float]) -> Alert | None:
    if len(history) < MIN_HISTORY_POINTS:
        print(
            f"[warmup] {snapshot.name}: insufficient historical data to build alert. "
            f"({len(history)}/{MIN_HISTORY_POINTS})"
        )
        return None

    historical_median = median(history)
    historical_mean = mean(history)
    historical_min = min(history)

    std = pstdev(history) if len(history) > 1 else 0.0

    reasons = []

    drop_from_median = 1 - (snapshot.price / historical_median)

    if drop_from_median >= DROP_PCT_THRESHOLD:
        reasons.append(
            f"current price is {drop_from_median:.1%} below the historical median"
        )

    if std > 0:
        z_score = (historical_mean - snapshot.price) / std
        if z_score >= Z_SCORE_THRESHOLD:
            reasons.append(
                f"current price is {z_score:.2f} standard deviations below the historical mean"
            )

    if snapshot.price < historical_min:
        reasons.append("current price is the lowest recorded in history")

    if not reasons:
        print(
            f"[ok] {snapshot.name}: {snapshot.currency} {snapshot.price:.2f} "
            "is not significantly low compared to historical data"
            f"(median: {snapshot.currency} {historical_median:.2f}, "
            f"mean: {snapshot.currency} {historical_mean:.2f})"
        )
        return None

    return Alert(
        snapshot=snapshot,
        historical_median=round(historical_median, 2),
        historical_mean=round(historical_mean, 2),
        historical_min=round(historical_min, 2),
        historical_count=len(history),
        reason="; ".join(reasons),
    )


def alert_recently_sent(alert: Alert) -> bool:
    """Check if alert already sent. Allows up to 2 distinct price drops per site."""
    if not ALERTS_PATH.exists():
        return False

    cutoff = now_utc() - timedelta(days=ALERT_COOLDOWN_DAYS)
    recent_alerts: list[tuple[datetime, float]] = []

    with ALERTS_PATH.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                timestamp = datetime.fromisoformat(row["timestamp_utc"])
                price = float(row["price"])
            except Exception:
                continue

            if timestamp < cutoff:
                continue

            same_url = row.get("url") == alert.snapshot.url
            same_currency = row.get("currency") == alert.snapshot.currency

            if same_url and same_currency:
                recent_alerts.append((timestamp, price))

    recent_alerts.sort(key=lambda x: x[1])

    for _, price in recent_alerts[:2]:
        if math.isclose(price, alert.snapshot.price, rel_tol=0.01):
            return True

    return False


def send_email(alerts: list[Alert]) -> bool:
    if not alerts:
        return False

    if create_github_issue(alerts):
        return True

    if not email_configured():
        print("[notification] Alert generated, but no notification mechanism configured. Nothing sent.")
        return False

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ["SMTP_PORT"])
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    subject = f"[Udacity] {len(alerts)} Nanodegree(s) with low prices"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = email_to
    message.set_content(build_email_body(alerts))

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)

    print(f"[email] Sent to {email_to}.")
    return True


def create_github_issue(alerts: list[Alert]) -> bool:
    """
    Create a GitHub issue in the current repository when running in Actions.
    Requires `GITHUB_REPOSITORY` (owner/repo) and `GITHUB_TOKEN` environment variables.
    """
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")

    if not repo or not token:
        return False

    title = f"[Udacity] {len(alerts)} Nanodegree(s) with low prices"
    body_lines = ["Low prices found for Udacity Nanodegrees.", ""]

    for alert in alerts:
        snapshot = alert.snapshot
        body_lines.extend(
            [
                f"Course: {snapshot.name}",
                f"Current Price: {snapshot.currency} {snapshot.price:.2f}",
                f"Original Price: {snapshot.currency} {snapshot.original_price:.2f}"
                if snapshot.original_price is not None
                else "Original Price: n/a",
                f"Discount: {snapshot.currency} {snapshot.discount_amount:.2f} ({snapshot.discount_percent:.2f}%)"
                if snapshot.discount_amount is not None and snapshot.discount_percent is not None
                else "Discount: n/a",
                f"Historical Median: {snapshot.currency} {alert.historical_median:.2f}",
                f"Historical Mean: {snapshot.currency} {alert.historical_mean:.2f}",
                f"Historical Minimum: {snapshot.currency} {alert.historical_min:.2f}",
                f"History Points: {alert.historical_count}",
                f"Alert Reason: {alert.reason}",
                f"URL: {snapshot.url}",
                "",
                "---",
                "",
            ]
        )

    body = "\n".join(body_lines)

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "body": body}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            issue_url = resp.json().get("html_url")
            print(f"[github] Created issue: {issue_url}")
            return True
        else:
            print(
                f"[github] Failed to create issue: {resp.status_code} {resp.text}")
            return False
    except Exception as exc:
        print(f"[github] Exception while creating issue: {exc}")
        return False


def email_configured() -> bool:
    required_vars = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "EMAIL_FROM",
        "EMAIL_TO",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"[email] Missing variables: {', '.join(missing)}")
        return False

    return True


def build_email_body(alerts: list[Alert]) -> str:
    lines = [
        "Low prices found for Udacity Nanodegrees.",
        "",
    ]

    for alert in alerts:
        snapshot = alert.snapshot

        lines.extend(
            [
                f"Course: {snapshot.name}",
                f"Current Price: {snapshot.currency} {snapshot.price:.2f}",
                f"Original Price: {snapshot.currency} {snapshot.original_price:.2f}"
                if snapshot.original_price is not None
                else "Original Price: n/a",
                f"Discount: {snapshot.currency} {snapshot.discount_amount:.2f} ({snapshot.discount_percent:.2f}%)"
                if snapshot.discount_amount is not None and snapshot.discount_percent is not None
                else "Discount: n/a",
                f"Historical Median: {snapshot.currency} {alert.historical_median:.2f}",
                f"Historical Mean: {snapshot.currency} {alert.historical_mean:.2f}",
                f"Historical Minimum: {snapshot.currency} {alert.historical_min:.2f}",
                f"History Points: {alert.historical_count}",
                f"Alert Reason: {alert.reason}",
                f"URL: {snapshot.url}",
                f"Context extracted: {snapshot.context}",
                "",
                "-" * 72,
                "",
            ]
        )

    return "\n".join(lines)


def append_alert(alert: Alert) -> None:
    fieldnames = [
        "timestamp_utc",
        "name",
        "url",
        "currency",
        "price",
        "historical_median",
        "historical_mean",
        "historical_min",
        "historical_count",
        "reason",
    ]

    ensure_csv(ALERTS_PATH, fieldnames)

    with ALERTS_PATH.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writerow(
            {
                "timestamp_utc": now_utc().isoformat(timespec="seconds"),
                "name": alert.snapshot.name,
                "url": alert.snapshot.url,
                "currency": alert.snapshot.currency,
                "price": f"{alert.snapshot.price:.2f}",
                "historical_median": f"{alert.historical_median:.2f}",
                "historical_mean": f"{alert.historical_mean:.2f}",
                "historical_min": f"{alert.historical_min:.2f}",
                "historical_count": alert.historical_count,
                "reason": alert.reason,
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
