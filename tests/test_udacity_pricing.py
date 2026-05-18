"""Tests for udacity_pricing module."""

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
