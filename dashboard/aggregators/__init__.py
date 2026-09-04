"""Dashboard aggregators for gathering data from different modules."""

from .base_aggregator import BaseAggregator
from .favourites_aggregator import FavouritesAggregator
from .fixtures_aggregator import FixturesAggregator
from .markets_aggregator import MarketsAggregator
from .memberships_aggregator import MembershipsAggregator
from .notifications_aggregator import NotificationsAggregator
from .profile_aggregator import ProfileAggregator
from .store_aggregator import StoreAggregator
from .wallet_aggregator import WalletAggregator

__all__ = [
    "BaseAggregator",
    "FixturesAggregator",
    "FavouritesAggregator",
    "MarketsAggregator",
    "MembershipsAggregator",
    "NotificationsAggregator",
    "ProfileAggregator",
    "StoreAggregator",
    "WalletAggregator",
]
