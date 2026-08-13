from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from discovery.models import PlayerProfile
from fantasy.models import FantasyLeague, FantasyPlayer, FantasyTeam, FantasyTeamPlayer
from notifications.models import Notification, NotificationCategory
from sports.models import Participant

from .test_fantasy import domain  # noqa: F401 -- shared pytest fixture


@pytest.fixture
def fantasy_notifications(db):
    return NotificationCategory.objects.create(
        code="FANTASY_TEAM_UPDATES",
        name="Fantasy team updates",
        default_enabled=True,
        is_active=True,
    )


def test_transfer_saved_creates_one_notification(domain, fantasy_notifications):  # noqa: F811
    fantasy, players, gameweek = domain
    fantasy.starting_lineup_size = 2
    fantasy.bench_size = 0
    fantasy.formation_rules = {
        "Keeper": {"min": 1, "max": 1},
        "Forward": {"min": 1, "max": 1},
    }
    fantasy.save()
    participant = Participant.objects.create(
        sport=fantasy.competition.sport, kind=Participant.Kind.ATHLETE, name="Replacement"
    )
    PlayerProfile.objects.create(participant=participant, position="Forward")
    replacement = FantasyPlayer.objects.create(
        fantasy_competition=fantasy,
        player=participant,
        position="Forward",
        price=Decimal("5"),
    )
    user = get_user_model().objects.create_user(username="transfer-notified")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Transfer XI", budget_remaining=10
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=players[0],
        is_starter=True,
        is_captain=True,
        purchase_price=5,
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=players[1],
        is_starter=True,
        is_vice_captain=True,
        purchase_price=5,
    )
    client = APIClient()
    client.force_authenticate(user)
    payload = {
        "gameweek": str(gameweek.id),
        "player_out": str(players[1].id),
        "player_in": str(replacement.id),
    }
    assert client.post(f"/api/v1/fantasy/teams/{team.id}/transfer/", payload).status_code == 200
    assert client.post(f"/api/v1/fantasy/teams/{team.id}/transfer/", payload).status_code == 400
    assert (
        Notification.objects.filter(recipient=user, event_type="FANTASY_TRANSFER_SAVED").count()
        == 1
    )


def test_league_join_creates_one_notification_when_join_is_retried(
    domain,  # noqa: F811
    fantasy_notifications,
):
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(
        username="league-owner-notification", email="league-owner-notification@example.com"
    )
    fan = get_user_model().objects.create_user(
        username="league-member-notification", email="league-member-notification@example.com"
    )
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Public League", visibility="PUBLIC"
    )
    FantasyTeam.objects.create(
        owner=fan, fantasy_competition=fantasy, name="Member XI", budget_remaining=10
    )
    client = APIClient()
    client.force_authenticate(fan)
    url = f"/api/v1/fantasy/leagues/{league.id}/join/"
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 200
    assert (
        Notification.objects.filter(recipient=fan, event_type="FANTASY_LEAGUE_JOINED").count() == 1
    )


def test_gameweek_locked_and_finalized_notifications_are_singletons(
    domain,  # noqa: F811
    fantasy_notifications,
):
    fantasy, _, gameweek = domain
    admin = get_user_model().objects.create_superuser(
        username="lifecycle-admin", email="lifecycle-admin@example.com"
    )
    fan = get_user_model().objects.create_user(
        username="lifecycle-fan", email="lifecycle-fan@example.com"
    )
    FantasyTeam.objects.create(
        owner=fan, fantasy_competition=fantasy, name="Lifecycle XI", budget_remaining=10
    )
    client = APIClient()
    client.force_authenticate(admin)
    transition_url = f"/api/v1/fantasy/gameweeks/{gameweek.id}/transition/"
    assert client.post(transition_url, {"status": "LOCKED"}, format="json").status_code == 200
    assert client.post(transition_url, {"status": "LOCKED"}, format="json").status_code == 400
    assert (
        Notification.objects.filter(recipient=fan, event_type="FANTASY_GAMEWEEK_LOCKED").count()
        == 1
    )

    gameweek.status = "SCORING"
    gameweek.save(update_fields=["status"])
    finalize_url = f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/"
    assert client.post(finalize_url).status_code == 200
    assert client.post(finalize_url).status_code == 400
    assert (
        Notification.objects.filter(recipient=fan, event_type="FANTASY_GAMEWEEK_FINALIZED").count()
        == 1
    )
