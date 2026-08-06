"""Analytics service for club analytics aggregation."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from clubs.models import (
    ClubAnalytics,
    Membership,
    StoreOrder,
    TicketOrder,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics operations."""

    @staticmethod
    def record_metric(club, metric_type, value, currency="UGX", metadata=None, date=None):
        """Record a daily analytics metric."""
        if date is None:
            date = timezone.now().date()

        analytics, created = ClubAnalytics.objects.update_or_create(
            club=club,
            metric_type=metric_type,
            date=date,
            defaults={
                "value": value,
                "currency": currency,
                "metadata": metadata or {},
            },
        )
        return analytics

    @staticmethod
    def get_fan_growth(club, start_date=None, end_date=None):
        """Get fan growth metrics."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.FAN_GROWTH,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def get_membership_sales(club, start_date=None, end_date=None):
        """Get membership sales metrics."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.MEMBERSHIP_SALES,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def get_ticket_sales(club, start_date=None, end_date=None):
        """Get ticket sales metrics."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.TICKET_SALES,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def get_merchandise_sales(club, start_date=None, end_date=None):
        """Get merchandise sales metrics."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.MERCHANDISE_SALES,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def get_revenue_summary(club, start_date=None, end_date=None):
        """Get revenue summary."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.REVENUE,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def get_inventory_performance(club, start_date=None, end_date=None):
        """Get inventory performance metrics."""
        if not start_date:
            start_date = timezone.now().date() - timedelta(days=30)
        if not end_date:
            end_date = timezone.now().date()

        return ClubAnalytics.objects.filter(
            club=club,
            metric_type=ClubAnalytics.MetricType.INVENTORY_PERFORMANCE,
            date__range=[start_date, end_date],
        ).order_by("date")

    @staticmethod
    def calculate_daily_metrics(club, target_date=None):
        """Calculate and store daily metrics."""
        if target_date is None:
            target_date = timezone.now().date()

        # Membership sales
        membership_count = Membership.objects.filter(
            plan__club=club,
            created_at__date=target_date,
            status=Membership.Status.ACTIVE,
        ).count()
        AnalyticsService.record_metric(
            club, ClubAnalytics.MetricType.MEMBERSHIP_SALES, membership_count, date=target_date
        )

        # Ticket sales
        ticket_revenue = (
            TicketOrder.objects.filter(
                product__club=club,
                created_at__date=target_date,
                status=TicketOrder.OrderStatus.PAID,
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )
        AnalyticsService.record_metric(
            club, ClubAnalytics.MetricType.TICKET_SALES, ticket_revenue, date=target_date
        )

        # Merchandise sales
        merchandise_revenue = (
            StoreOrder.objects.filter(
                club=club,
                created_at__date=target_date,
                status=StoreOrder.OrderStatus.PAID,
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )
        AnalyticsService.record_metric(
            club, ClubAnalytics.MetricType.MERCHANDISE_SALES, merchandise_revenue, date=target_date
        )

        # Total revenue
        total_revenue = (ticket_revenue or 0) + (merchandise_revenue or 0)
        AnalyticsService.record_metric(
            club, ClubAnalytics.MetricType.REVENUE, total_revenue, date=target_date
        )

        return target_date


analytics_service = AnalyticsService()
