"""Dashboard aggregators for gathering data from different modules."""

from .base_aggregator import BaseAggregator
from .favourites_aggregator import FavouritesAggregator
from .fixtures_aggregator import FixturesAggregator
from .markets_aggregator import MarketsAggregator
from .notifications_aggregator import NotificationsAggregator
from .profile_aggregator import ProfileAggregator
from .wallet_aggregator import WalletAggregator

__all__ = [
    "BaseAggregator",
    "FixturesAggregator",
    "FavouritesAggregator",
    "MarketsAggregator",
    "NotificationsAggregator",
    "ProfileAggregator",
    "WalletAggregator",
]
