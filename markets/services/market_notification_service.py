import logging

from django.db import transaction

logger = logging.getLogger(__name__)


class MarketNotificationService:
    """Best-effort participant notifications scheduled only after commit."""

    @staticmethod
    def schedule(
        *,
        recipient,
        category,
        event_type,
        title,
        message,
        key,
        data=None,
        market_id=None,
        mandatory=False,
        severity="INFO",
    ):
        recipient_id = recipient.pk

        def create():
            try:
                from django.contrib.auth import get_user_model

                from notifications.services.notification_service import NotificationService

                NotificationService.create(
                    recipient=get_user_model().objects.get(pk=recipient_id),
                    category_code=category,
                    event_type=event_type,
                    title=title,
                    message=message,
                    deduplication_key=key,
                    data=data or {},
                    market_id=market_id,
                    mandatory=mandatory,
                    severity=severity,
                )
            except Exception:
                logger.exception("Unable to create market notification")

        transaction.on_commit(create)

    @classmethod
    def order_accepted(cls, order):
        cls.schedule(
            recipient=order.user,
            category="MARKET_ORDERS",
            event_type="ORDER_ACCEPTED",
            title="Order accepted",
            message="Your market order was accepted.",
            key=f"market-order:{order.id}:accepted",
            market_id=order.market_id,
            data={"order_id": str(order.id), "side": order.side},
        )

    @classmethod
    def order_cancelled(cls, order):
        cls.schedule(
            recipient=order.user,
            category="MARKET_ORDERS",
            event_type="ORDER_CANCELLED",
            title="Order cancelled",
            message="Your market order was cancelled.",
            key=f"market-order:{order.id}:cancelled",
            market_id=order.market_id,
            data={"order_id": str(order.id)},
        )

    @classmethod
    def fill(cls, fill):
        for role, order in (("buyer", fill.buy_order), ("seller", fill.sell_order)):
            complete = order.status == order.Status.FILLED
            cls.schedule(
                recipient=order.user,
                category="MARKET_TRADES",
                event_type="ORDER_FULLY_FILLED" if complete else "ORDER_PARTIALLY_FILLED",
                title="Order filled" if complete else "Order partially filled",
                message="Your order received a market fill.",
                key=f"market-fill:{fill.id}:{role}",
                market_id=fill.market_id,
                data={
                    "fill_id": str(fill.id),
                    "side": order.side,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                },
            )

    @classmethod
    def expired(cls, audit):
        cls.schedule(
            recipient=audit.market_order.user,
            category="MARKET_ORDERS",
            event_type="ORDER_EXPIRED",
            title="Order expired",
            message=f"Your remaining order quantity of {audit.expired_quantity} expired.",
            key=f"market-order-expiry:{audit.id}",
            market_id=audit.market_order.market_id,
            data={
                "expiry_audit_id": str(audit.id),
                "expired_quantity": str(audit.expired_quantity),
            },
        )

    @classmethod
    def settlement(cls, record):
        cls.schedule(
            recipient=record.participant,
            category="MARKET_SETTLEMENTS",
            event_type="SETTLEMENT_WIN" if record.was_winner else "SETTLEMENT_LOSS",
            title="Market settlement",
            message=(f"Settlement completed with net payout {record.net_payout_amount}."),
            key=f"market-position-settlement:{record.id}",
            market_id=record.market_settlement.market_id,
            data={
                "position_settlement_id": str(record.id),
                "was_winner": record.was_winner,
                "net_payout_amount": str(record.net_payout_amount),
            },
            mandatory=True,
        )

    @classmethod
    def refund(cls, record):
        cls.schedule(
            recipient=record.participant,
            category="MARKET_SETTLEMENTS",
            event_type="VOID_REFUND",
            title="Void refund",
            message=f"A void refund of {record.net_refund_amount} was completed.",
            key=f"market-position-refund:{record.id}",
            market_id=record.market_void_refund.market_id,
            data={
                "position_refund_id": str(record.id),
                "net_refund_amount": str(record.net_refund_amount),
            },
            mandatory=True,
        )
