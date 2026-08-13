from rest_framework.routers import DefaultRouter

from .views import (
    CompetitionViewSet,
    CorrectionViewSet,
    GameweekViewSet,
    LeagueViewSet,
    PlayerViewSet,
    ScoringRuleViewSet,
    TeamViewSet,
)

app_name = "fantasy"
router = DefaultRouter()
router.register("fantasy/competitions", CompetitionViewSet, basename="fantasy-competition")
router.register("fantasy/gameweeks", GameweekViewSet, basename="fantasy-gameweek")
router.register("fantasy/players", PlayerViewSet, basename="fantasy-player")
router.register("fantasy/teams", TeamViewSet, basename="fantasy-team")
router.register("fantasy/leagues", LeagueViewSet, basename="fantasy-league")
router.register("fantasy/admin/scoring-rules", ScoringRuleViewSet, basename="fantasy-scoring-rule")
router.register("fantasy/admin/corrections", CorrectionViewSet, basename="fantasy-correction")
urlpatterns = router.urls
