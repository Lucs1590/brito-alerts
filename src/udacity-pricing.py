import csv
import math
import os
import re
import smtplib
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

# Critérios de alerta
MIN_HISTORY_POINTS = int(os.getenv("MIN_HISTORY_POINTS", "5"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "180"))

# Ex.: 0.25 = alerta quando o preço atual estiver 25% abaixo da mediana histórica
DROP_PCT_THRESHOLD = float(os.getenv("DROP_PCT_THRESHOLD", "0.25"))

# Ex.: 1.25 = alerta quando estiver 1.25 desvios-padrão abaixo da média
Z_SCORE_THRESHOLD = float(os.getenv("Z_SCORE_THRESHOLD", "1.25"))

# Evita capturar valores irrelevantes como "0", "7 days", etc.
MIN_VALID_PRICE = float(os.getenv("MIN_VALID_PRICE", "50"))

# Evita enviar e-mail repetido todo dia para o mesmo preço
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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_amount(value: str) -> float:
    """
    Normaliza valores como:
    - 399
    - 399.00
    - 399,00
    - 1,299.00
    - 1.299,00
    """
    value = value.strip()

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            # Formato brasileiro: 1.299,00
            value = value.replace(".", "").replace(",", ".")
        else:
            # Formato americano: 1,299.00
            value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        if len(parts[-1]) == 2:
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    else:
        # Pode ser 1299 ou 1.299; se o último bloco tiver 3 dígitos, assume separador de milhar.
        parts = value.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3:
            value = value.replace(".", "")

    return float(value)


def extract_prices(text: str) -> list[PriceCandidate]:
    """
    Extrai valores monetários do texto visível da página.

    Captura exemplos:
    - $399
    - US$399
    - USD 399
    - R$ 1.299,00
    - BRL 1299
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


def deduplicate_prices(candidates: Iterable[PriceCandidate]) -> list[PriceCandidate]:
    seen = set()
    unique: list[PriceCandidate] = []

    for candidate in candidates:
        key = (candidate.currency, round(candidate.amount, 2))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    return unique


def choose_relevant_price(candidates: list[PriceCandidate]) -> PriceCandidate:
    """
    Como a página pode exibir preço cheio e preço promocional,
    escolhemos o menor preço monetário válido encontrado.
    """
    if not candidates:
        raise ValueError("Nenhum preço monetário válido encontrado na página.")

    return min(candidates, key=lambda item: item.amount)


def get_page_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1200},
            locale="en-US",
        )

        try:
            page.goto(url, wait_until="networkidle", timeout=60_000)

            # Pequena tolerância para páginas que ainda atualizam conteúdo após networkidle.
            page.wait_for_timeout(2_000)

            # Tenta fechar banners comuns de cookie, se existirem.
            for label in ["Accept", "Accept All", "I agree", "Agree", "Got it"]:
                try:
                    page.get_by_role("button", name=re.compile(
                        label, re.I)).click(timeout=1_000)
                    break
                except Exception:
                    pass

            text = page.locator("body").inner_text(timeout=15_000)
            return text

        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"Timeout ao abrir a página: {url}") from exc
        finally:
            browser.close()


def get_price(site: dict) -> PriceSnapshot:
    text = get_page_text(site["url"])
    candidates = extract_prices(text)
    selected = choose_relevant_price(candidates)

    return PriceSnapshot(
        timestamp_utc=now_utc().isoformat(timespec="seconds"),
        name=site["name"],
        url=site["url"],
        currency=selected.currency,
        price=round(selected.amount, 2),
        raw=selected.raw,
        context=selected.context,
    )


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()


def append_snapshot(snapshot: PriceSnapshot) -> None:
    fieldnames = [
        "timestamp_utc",
        "name",
        "url",
        "currency",
        "price",
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
                "raw": snapshot.raw,
                "context": snapshot.context,
            }
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


def build_alert(snapshot: PriceSnapshot, history: list[float]) -> Alert | None:
    if len(history) < MIN_HISTORY_POINTS:
        print(
            f"[warmup] {snapshot.name}: histórico insuficiente "
            f"({len(history)}/{MIN_HISTORY_POINTS})."
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
            f"preço atual está {drop_from_median:.1%} abaixo da mediana histórica"
        )

    if std > 0:
        z_score = (historical_mean - snapshot.price) / std
        if z_score >= Z_SCORE_THRESHOLD:
            reasons.append(
                f"preço atual está {z_score:.2f} desvios-padrão abaixo da média histórica"
            )

    if snapshot.price < historical_min:
        reasons.append("preço atual é o menor já registrado no histórico")

    if not reasons:
        print(
            f"[ok] {snapshot.name}: {snapshot.currency} {snapshot.price:.2f} "
            f"não atingiu critério de alerta."
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
    if not ALERTS_PATH.exists():
        return False

    cutoff = now_utc() - timedelta(days=ALERT_COOLDOWN_DAYS)

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

            # Considera repetido se o preço for praticamente igual.
            same_price = math.isclose(
                price, alert.snapshot.price, rel_tol=0.01)

            if same_url and same_currency and same_price:
                return True

    return False


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
        print(f"[email] Variáveis ausentes: {', '.join(missing)}")
        return False

    return True


def build_email_body(alerts: list[Alert]) -> str:
    lines = [
        "Foram encontrados preços relevantemente baixos em Nanodegrees da Udacity.",
        "",
    ]

    for alert in alerts:
        snapshot = alert.snapshot

        lines.extend(
            [
                f"Curso: {snapshot.name}",
                f"Preço atual: {snapshot.currency} {snapshot.price:.2f}",
                f"Mediana histórica: {snapshot.currency} {alert.historical_median:.2f}",
                f"Média histórica: {snapshot.currency} {alert.historical_mean:.2f}",
                f"Menor preço histórico anterior: {snapshot.currency} {alert.historical_min:.2f}",
                f"Pontos no histórico: {alert.historical_count}",
                f"Motivo do alerta: {alert.reason}",
                f"URL: {snapshot.url}",
                f"Contexto extraído: {snapshot.context}",
                "",
                "-" * 72,
                "",
            ]
        )

    return "\n".join(lines)


def send_email(alerts: list[Alert]) -> bool:
    if not alerts:
        return False

    if not email_configured():
        print("[email] Alerta gerado, mas e-mail não configurado. Nada enviado.")
        return False

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ["SMTP_PORT"])
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    subject = f"[Udacity] {len(alerts)} Nanodegree(s) com preço baixo"

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

    print(f"[email] Enviado para {email_to}.")
    return True


def main() -> int:
    generated_alerts: list[Alert] = []
    errors: list[str] = []
    successful_snapshots = 0

    for site in SITES:
        print(f"[check] Coletando preço: {site['name']}")

        try:
            snapshot = get_price(site)

            # Carrega histórico antes de salvar o preço atual,
            # para não comparar a execução atual com ela mesma.
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
                    f"[skip] Alerta recente já enviado para {snapshot.name}.")
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
    print("Resumo:")
    print(f"- Páginas processadas com sucesso: {successful_snapshots}")
    print(f"- Alertas gerados: {len(generated_alerts)}")
    print(f"- E-mail enviado: {'sim' if email_sent else 'não'}")

    if errors:
        print("- Erros:")
        for error in errors:
            print(f"  - {error}")

    return 0 if successful_snapshots > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
