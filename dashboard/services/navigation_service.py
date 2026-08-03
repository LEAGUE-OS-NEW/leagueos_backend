"""Navigation service for building dynamic navigation menus.

Builds hierarchical navigation from database with permission filtering.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.models import NavigationMenu

User = get_user_model()
logger = logging.getLogger(__name__)


class NavigationService:
    """Service for building dynamic navigation menus.

    Reads navigation structure from database and filters based on
    user permissions. Supports hierarchical parent-child relationships.
    """

    @staticmethod
    def _user_has_permission(user: User, permission: str) -> bool:
        """Check if user has the required permission.

        Args:
            user: The user to check permissions for
            permission: Permission string to check

        Returns:
            True if user has permission or no permission required
        """
        if not permission:
            return True

        if not user.is_authenticated:
            return False

        # Superusers have all permissions
        if user.is_superuser:
            return True

        # Check user permissions
        return user.has_perm(permission)

    @classmethod
    def get_navigation(cls, user: User) -> list[dict]:
        """Get navigation menu for the user.

        Args:
            user: The user to get navigation for

        Returns:
            Hierarchical navigation structure
        """
        # Get all active navigation items
        nav_items = NavigationMenu.objects.filter(is_active=True).select_related("parent")

        # Filter by permissions
        accessible_items = []
        for item in nav_items:
            if cls._user_has_permission(user, item.permission_required):
                accessible_items.append(item)

        # Build hierarchical tree
        tree = cls._build_tree(accessible_items)

        logger.debug("Navigation built for user %s: %d items", user.id, len(tree))
        return tree

    @classmethod
    def _build_tree(cls, items: list[NavigationMenu]) -> list[dict]:
        """Build hierarchical tree from flat list of navigation items.

        Args:
            items: List of NavigationMenu instances

        Returns:
            Hierarchical tree structure
        """
        # Create lookup by parent
        item_map = {}
        for item in items:
            item_data = {
                "id": str(item.id),
                "name": item.name,
                "route": item.route,
                "icon": item.icon,
                "display_order": item.display_order,
                "permission_required": item.permission_required,
                "children": [],
            }
            item_map[item.id] = item_data

        # Build tree
        tree = []
        for item in items:
            item_data = item_map[item.id]
            if item.parent_id and item.parent_id in item_map:
                # Add as child
                item_map[item.parent_id]["children"].append(item_data)
            else:
                # Add to root
                tree.append(item_data)

        # Sort by display_order
        tree.sort(key=lambda x: x["display_order"])
        for item_data in item_map.values():
            item_data["children"].sort(key=lambda x: x["display_order"])

        return tree
