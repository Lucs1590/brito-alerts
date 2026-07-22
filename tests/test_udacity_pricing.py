"""Tests for udacity_pricing module."""

import csv
import pytest
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestUdacityPricing:
    """Test suite for Udacity pricing monitor."""

    def test_import_module(self):
        """Test that the udacity_pricing module can be imported."""
        try:
            import udacity_pricing  # noqa: F401
        except ImportError as e:
            pytest.fail(f"Failed to import udacity_pricing: {e}")

    def test_sites_configuration(self):
        """Test that SITES configuration is properly set."""
        import udacity_pricing

        assert hasattr(udacity_pricing, "SITES")
        assert len(udacity_pricing.SITES) > 0

        for site in udacity_pricing.SITES:
            assert "name" in site
            assert "url" in site
            assert site["url"].startswith("https://")

    def test_environment_variables(self):
        """Test that environment variables are properly configured."""
        import udacity_pricing

        # Check that path variables are set
        assert hasattr(udacity_pricing, "HISTORY_PATH")
        assert hasattr(udacity_pricing, "ALERTS_PATH")

        # Check thresholds
        assert hasattr(udacity_pricing, "MIN_HISTORY_POINTS")
        assert hasattr(udacity_pricing, "LOOKBACK_DAYS")
        assert hasattr(udacity_pricing, "DROP_PCT_THRESHOLD")
        assert hasattr(udacity_pricing, "Z_SCORE_THRESHOLD")

    def test_price_candidate_dataclass(self):
        """Test PriceCandidate dataclass."""
        import udacity_pricing

        candidate = udacity_pricing.PriceCandidate(
            currency="USD",
            amount=100.0,
            raw="$100.00",
            context="test"
        )

        assert candidate.currency == "USD"
        assert candidate.amount == 100.0
        assert candidate.raw == "$100.00"
        assert candidate.context == "test"

    def test_choose_relevant_price_without_discount(self):
        """Keeps stable behavior when only one visible price exists."""
        import udacity_pricing

        candidates = [
            udacity_pricing.PriceCandidate(
                currency="USD",
                amount=399.0,
                raw="$399.00",
                context="Enroll now and start learning.",
            )
        ]

        selected = udacity_pricing.choose_relevant_price(candidates)

        assert selected.current.amount == 399.0
        assert selected.original is None
        assert selected.discount_amount is None
        assert selected.discount_percent is None

    def test_choose_relevant_price_with_discount_visible(self):
        """Prioritizes promotional price and computes discount metadata."""
        import udacity_pricing

        candidates = [
            udacity_pricing.PriceCandidate(
                currency="USD",
                amount=249.0,
                raw="$249.00",
                context="Limited time discount price.",
            ),
            udacity_pricing.PriceCandidate(
                currency="USD",
                amount=399.0,
                raw="$399.00",
                context="Original list price before discount.",
            ),
        ]

        selected = udacity_pricing.choose_relevant_price(candidates)

        assert selected.current.amount == 249.0
        assert selected.original is not None
        assert selected.original.amount == 399.0
        assert selected.discount_amount == pytest.approx(150.0, abs=0.01)
        assert selected.discount_percent == pytest.approx((150.0 / 399.0) * 100, abs=0.01)

    def test_choose_relevant_price_partial_structure(self):
        """Handles partial page structures with multiple prices safely."""
        import udacity_pricing

        candidates = [
            udacity_pricing.PriceCandidate(
                currency="USD",
                amount=329.0,
                raw="$329.00",
                context="now only today special offer",
            ),
            udacity_pricing.PriceCandidate(
                currency="USD",
                amount=499.0,
                raw="$499.00",
                context="some unrelated text",
            ),
        ]

        selected = udacity_pricing.choose_relevant_price(candidates)

        assert selected.current.amount == 329.0
        assert selected.original is not None
        assert selected.original.amount == 499.0

    def test_ensure_csv_migrates_existing_header(self, tmp_path):
        """Migrates an existing CSV header and preserves old row values."""
        import udacity_pricing

        csv_path = tmp_path / "udacity_prices.csv"
        old_fields = ["timestamp_utc", "name", "url", "currency", "price", "raw", "context"]
        new_fields = [
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

        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=old_fields)
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "name": "Course",
                    "url": "https://example.com",
                    "currency": "USD",
                    "price": "199.00",
                    "raw": "$199.00",
                    "context": "context",
                }
            )

        udacity_pricing.ensure_csv(csv_path, new_fields)

        with csv_path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)

        assert reader.fieldnames == new_fields
        assert len(rows) == 1
        assert rows[0]["price"] == "199.00"
        assert rows[0]["original_price"] == ""
        assert rows[0]["discount_amount"] == ""
        assert rows[0]["discount_percent"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
