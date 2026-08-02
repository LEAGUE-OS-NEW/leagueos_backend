"""Tests for dashboard aggregators."""

import pytest
from unittest.mock import patch, MagicMock

from dashboard.aggregators.base_aggregator import BaseAggregator
from dashboard.aggregators.profile_aggregator import ProfileAggregator
from dashboard.aggregators.favourites_aggregator import FavouritesAggregator
from dashboard.aggregators.notifications_aggregator import NotificationsAggregator
from dashboard.aggregators.fixtures_aggregator import FixturesAggregator
from dashboard.aggregators.markets_aggregator import MarketsAggregator
from dashboard.aggregators.wallet_aggregator import WalletAggregator


def test_base_aggregator_success_response():
    """Test base aggregator success response."""
    aggregator = BaseAggregator()
    aggregator.module_code = "test"
    result = aggregator._success_response({"key": "value"})

    assert result["status"] == "success"
    assert result["module"] == "test"
    assert result["data"]["key"] == "value"


def test_base_aggregator_error_response():
    """Test base aggregator error response."""
    aggregator = BaseAggregator()
    aggregator.module_code = "test"
    result = aggregator._error_response("Test error")

    assert result["status"] == "unavailable"
    assert result["module"] == "test"
    assert result["message"] == "Test error"


def test_base_aggregator_empty_response():
    """Test base aggregator empty response."""
    aggregator = BaseAggregator()
    aggregator.module_code = "test"
    result = aggregator._empty_response({"key": "value"})

    assert result["status"] == "success"
    assert result["module"] == "test"
    assert result["empty"] is True


def test_profile_aggregator_returns_data(user):
    """Test profile aggregator returns user data."""
    aggregator = ProfileAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert result["data"]["email"] == user.email


def test_profile_aggregator_handles_no_profile(user):
    """Test profile aggregator when profile doesn't exist."""
    # Delete user's profile if it exists
    if hasattr(user, "profile"):
        user.profile.delete()

    aggregator = ProfileAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert result["empty"] is True


def test_favourites_aggregator_returns_data(user):
    """Test favourites aggregator returns favourite data."""
    aggregator = FavouritesAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert "clubs" in result["data"]
    assert "sports" in result["data"]
    assert "competitions" in result["data"]


def test_notifications_aggregator_returns_data(user):
    """Test notifications aggregator returns notification data."""
    aggregator = NotificationsAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert "unread_count" in result["data"]
    assert "recent_notifications" in result["data"]


def test_fixtures_aggregator_returns_data(user):
    """Test fixtures aggregator returns fixture data."""
    aggregator = FixturesAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert "upcoming_fixtures" in result["data"]
    assert "count" in result["data"]


def test_markets_aggregator_returns_data(user):
    """Test markets aggregator returns market data."""
    aggregator = MarketsAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert "featured_markets" in result["data"]
    assert "count" in result["data"]


def test_wallet_aggregator_returns_data(user):
    """Test wallet aggregator returns wallet data."""
    aggregator = WalletAggregator()
    result = aggregator.aggregate(user)

    assert result["status"] == "success"
    assert "data" in result
    assert "balance" in result["data"]
    assert "currency" in result["data"]


def test_aggregator_handles_exceptions(user):
    """Test that aggregators handle exceptions gracefully."""
    aggregator = ProfileAggregator()

    with patch.object(aggregator, "_success_response", side_effect=Exception("Test error")):
        result = aggregator.aggregate(user)

    assert result["status"] == "unavailable"
    assert "message" in result