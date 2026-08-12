from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import transaction
from django.utils import timezone

from authentication.services.permission_service import (
    PermissionService,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketScope,
    MarketTemplate,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from sports.models import (
    Competition,
    EventParticipant,
    Participant,
    Sport,
    SportingEvent,
)

DEMO_SOURCE = "LEAGUE_OS_DEMO"


COMPETITIONS = [
    {
        "sport": "FOOTBALL",
        "name": "Uganda Premier League",
        "reference": "competition:upl",
    },
    {
        "sport": "RUGBY",
        "name": "Nile Special Rugby Premiership",
        "reference": "competition:nsl-rugby",
    },
    {
        "sport": "BASKETBALL",
        "name": "National Basketball League Uganda",
        "reference": "competition:nbl-uganda",
    },
]


PARTICIPANTS = {
    "FOOTBALL": [
        "Vipers SC",
        "KCCA FC",
        "SC Villa",
        "Express FC",
        "BUL FC",
        "URA FC",
    ],
    "RUGBY": [
        "KOBS Rugby Club",
        "Platinum Credit Heathens",
        "Black Pirates",
        "Toyota Buffaloes",
        "Rhinos RFC",
        "Mongers RFC",
    ],
    "BASKETBALL": [
        "City Oilers",
        "Namuwongo Blazers",
        "UCU Canons",
        "KIU Titans",
        "JT Jaguars",
        "Kampala Rockets",
    ],
}


EVENTS = [
    {
        "reference": "event:football:vipers-kcca",
        "sport": "FOOTBALL",
        "competition": "Uganda Premier League",
        "home": "Vipers SC",
        "away": "KCCA FC",
        "days": 4,
        "venue": "St Mary's Stadium, Kitende",
    },
    {
        "reference": "event:football:villa-express",
        "sport": "FOOTBALL",
        "competition": "Uganda Premier League",
        "home": "SC Villa",
        "away": "Express FC",
        "days": 6,
        "venue": "Mandela National Stadium",
    },
    {
        "reference": "event:football:bul-ura",
        "sport": "FOOTBALL",
        "competition": "Uganda Premier League",
        "home": "BUL FC",
        "away": "URA FC",
        "days": 8,
        "venue": "FUFA Technical Centre",
    },
    {
        "reference": "event:rugby:kobs-heathens",
        "sport": "RUGBY",
        "competition": "Nile Special Rugby Premiership",
        "home": "KOBS Rugby Club",
        "away": "Platinum Credit Heathens",
        "days": 5,
        "venue": "Legends Rugby Grounds",
    },
    {
        "reference": "event:rugby:pirates-buffaloes",
        "sport": "RUGBY",
        "competition": "Nile Special Rugby Premiership",
        "home": "Black Pirates",
        "away": "Toyota Buffaloes",
        "days": 7,
        "venue": "Kings Park",
    },
    {
        "reference": "event:rugby:rhinos-mongers",
        "sport": "RUGBY",
        "competition": "Nile Special Rugby Premiership",
        "home": "Rhinos RFC",
        "away": "Mongers RFC",
        "days": 9,
        "venue": "Legends Rugby Grounds",
    },
    {
        "reference": "event:basketball:oilers-blazers",
        "sport": "BASKETBALL",
        "competition": "National Basketball League Uganda",
        "home": "City Oilers",
        "away": "Namuwongo Blazers",
        "days": 3,
        "venue": "Lugogo Indoor Arena",
    },
    {
        "reference": "event:basketball:ucu-kiu",
        "sport": "BASKETBALL",
        "competition": "National Basketball League Uganda",
        "home": "UCU Canons",
        "away": "KIU Titans",
        "days": 6,
        "venue": "Lugogo Indoor Arena",
    },
    {
        "reference": "event:basketball:jaguars-rockets",
        "sport": "BASKETBALL",
        "competition": "National Basketball League Uganda",
        "home": "JT Jaguars",
        "away": "Kampala Rockets",
        "days": 8,
        "venue": "Lugogo Indoor Arena",
    },
]


TEMPLATES = [
    {
        "code": "MATCH_RESULT_EVENT",
        "category": "Match Result",
        "scope_type": MarketScope.EVENT,
        "name": "Match Result",
        "question_template": ("Will {home_team} beat {away_team}?"),
    },
    {
        "code": "TOTALS_EVENT",
        "category": "Totals",
        "scope_type": MarketScope.EVENT,
        "name": "Match Total",
        "question_template": ("Will the match finish above the selected total?"),
    },
    {
        "code": "HANDICAP_EVENT",
        "category": "Handicap / Spread",
        "scope_type": MarketScope.EVENT,
        "name": "Handicap / Spread",
        "question_template": ("Will the selected team cover the handicap?"),
    },
    {
        "code": "MARGIN_EVENT",
        "category": "Correct Score / Margin",
        "scope_type": MarketScope.EVENT,
        "name": "Winning Margin",
        "question_template": ("Will the winning margin fall within the selected range?"),
    },
    {
        "code": "TEAM_PROP",
        "category": "Player / Team Prop",
        "scope_type": MarketScope.PARTICIPANT,
        "name": "Player / Team Prop",
        "question_template": ("Will the participant achieve the selected target?"),
    },
    {
        "code": "TOURNAMENT_SEASON",
        "category": "Tournament / Season",
        "scope_type": MarketScope.COMPETITION,
        "name": "Tournament / Season",
        "question_template": ("Will the selected participant win the competition?"),
    },
    {
        "code": "EVENT_OCCURRENCE",
        "category": "Event / Occurrence",
        "scope_type": MarketScope.EVENT,
        "name": "Event / Occurrence",
        "question_template": ("Will the selected event occur during the match?"),
    },
]


MARKETS = [
    {
        "event": "event:football:vipers-kcca",
        "category": "Match Result",
        "question": "Will Vipers SC beat KCCA FC?",
        "yes": "Vipers SC win",
        "no": "KCCA FC win or draw",
        "featured": True,
    },
    {
        "event": "event:football:vipers-kcca",
        "category": "Totals",
        "question": ("Will Vipers SC vs KCCA FC have over 2.5 goals?"),
        "yes": "Over 2.5 goals",
        "no": "2 goals or fewer",
        "featured": True,
    },
    {
        "event": "event:football:villa-express",
        "category": "Event / Occurrence",
        "question": ("Will both SC Villa and Express FC score?"),
        "yes": "Both teams score",
        "no": "At least one team does not score",
        "featured": False,
    },
    {
        "event": "event:football:bul-ura",
        "category": "Handicap / Spread",
        "question": ("Will BUL FC cover a -1 goal handicap against URA FC?"),
        "yes": "BUL FC covers",
        "no": "BUL FC does not cover",
        "featured": False,
    },
    {
        "event": "event:rugby:kobs-heathens",
        "category": "Match Result",
        "question": ("Will KOBS Rugby Club beat Platinum Credit Heathens?"),
        "yes": "KOBS win",
        "no": "Heathens win or draw",
        "featured": True,
    },
    {
        "event": "event:rugby:kobs-heathens",
        "category": "Totals",
        "question": ("Will KOBS vs Heathens have over 42.5 total points?"),
        "yes": "Over 42.5",
        "no": "42 points or fewer",
        "featured": True,
    },
    {
        "event": "event:rugby:pirates-buffaloes",
        "category": "Correct Score / Margin",
        "question": ("Will Black Pirates win by 1 to 7 points?"),
        "yes": "Pirates by 1-7",
        "no": "Any other result",
        "featured": False,
    },
    {
        "event": "event:rugby:rhinos-mongers",
        "category": "Event / Occurrence",
        "question": ("Will Rhinos vs Mongers include a yellow card?"),
        "yes": "A yellow card is shown",
        "no": "No yellow card",
        "featured": False,
    },
    {
        "event": "event:basketball:oilers-blazers",
        "category": "Match Result",
        "question": ("Will City Oilers beat Namuwongo Blazers?"),
        "yes": "City Oilers win",
        "no": "Namuwongo Blazers win",
        "featured": True,
    },
    {
        "event": "event:basketball:oilers-blazers",
        "category": "Totals",
        "question": ("Will City Oilers vs Blazers exceed 155.5 total points?"),
        "yes": "Over 155.5",
        "no": "155 points or fewer",
        "featured": True,
    },
    {
        "event": "event:basketball:ucu-kiu",
        "category": "Handicap / Spread",
        "question": ("Will UCU Canons cover a -4.5 point spread?"),
        "yes": "UCU covers",
        "no": "UCU does not cover",
        "featured": False,
    },
    {
        "event": "event:basketball:jaguars-rockets",
        "category": "Event / Occurrence",
        "question": ("Will JT Jaguars score 80 or more points?"),
        "yes": "80+ points",
        "no": "79 points or fewer",
        "featured": False,
    },
]


class Command(BaseCommand):
    help = (
        "Seed realistic staging sports and market demo data. "
        "This command is manual-only and preserves existing rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help=("Required safety flag confirming that " "demo data should be written."),
        )
        parser.add_argument(
            "--creator-email",
            default="admin@leagueos.com",
            help=("Existing administrator used as the " "creator/approver of demo markets."),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Refusing to seed demo data without --confirm.")

        creator_email = options["creator_email"].strip()

        user_model = get_user_model()

        try:
            creator = user_model.objects.get(
                email__iexact=creator_email,
            )
        except user_model.DoesNotExist as error:
            raise CommandError(f"Creator account not found: {creator_email}") from error

        for permission in (
            "manage_market",
            "approve_market",
        ):
            if not PermissionService.has_permission(
                creator,
                permission,
            ):
                raise CommandError(f"{creator_email} does not have " f"{permission}.")

        sports = {
            sport.code: sport
            for sport in Sport.objects.filter(
                code__in=[
                    "FOOTBALL",
                    "RUGBY",
                    "BASKETBALL",
                ]
            )
        }

        missing_sports = {
            "FOOTBALL",
            "RUGBY",
            "BASKETBALL",
        } - set(sports)

        if missing_sports:
            raise CommandError(
                "Missing sports (run `python manage.py seed_sports` first): "
                + ", ".join(sorted(missing_sports))
            )

        required_categories = {item["category"] for item in TEMPLATES}

        categories = {
            category.name: category
            for category in (
                MarketCategory.objects.filter(
                    name__in=required_categories,
                    is_active=True,
                )
            )
        }

        missing_categories = required_categories - set(categories)

        if missing_categories:
            raise CommandError(
                "Missing market categories: "
                + ", ".join(
                    sorted(
                        missing_categories,
                    )
                )
                + ". Run seed_market_catalog first."
            )

        competitions = self._seed_competitions(
            sports,
        )
        participants = self._seed_participants(
            sports,
        )
        events = self._seed_events(
            sports=sports,
            competitions=competitions,
            participants=participants,
        )
        templates = self._seed_templates(
            categories,
        )

        created_markets = self._seed_event_markets(
            creator=creator,
            events=events,
            categories=categories,
            templates=templates,
        )

        created_markets += self._seed_long_horizon_markets(
            creator=creator,
            competitions=competitions,
            participants=participants,
            categories=categories,
            templates=templates,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Market demo seed complete. " f"New markets created: {created_markets}"
            )
        )

    def _seed_competitions(
        self,
        sports,
    ):
        result = {}

        for item in COMPETITIONS:
            competition, created = Competition.objects.get_or_create(
                source_name=DEMO_SOURCE,
                source_reference=item["reference"],
                defaults={
                    "sport": sports[item["sport"]],
                    "name": item["name"],
                    "country_code": "UG",
                    "is_active": True,
                    "is_verified": True,
                },
            )

            result[item["name"]] = competition

            if created:
                self.stdout.write(f"Created competition: " f"{competition.name}")

        return result

    def _seed_participants(
        self,
        sports,
    ):
        result = {}

        for sport_code, names in PARTICIPANTS.items():
            for name in names:
                reference = (
                    f"participant:" f"{sport_code.lower()}:" f"{name.lower().replace(' ', '-')}"
                )

                participant, created = Participant.objects.get_or_create(
                    source_name=DEMO_SOURCE,
                    source_reference=reference,
                    defaults={
                        "sport": sports[sport_code],
                        "kind": (Participant.Kind.TEAM),
                        "name": name,
                        "short_name": name,
                        "country_code": "UG",
                        "is_active": True,
                        "is_verified": True,
                    },
                )

                result[
                    (
                        sport_code,
                        name,
                    )
                ] = participant

                if created:
                    self.stdout.write(f"Created participant: " f"{participant.name}")

        return result

    def _seed_events(
        self,
        *,
        sports,
        competitions,
        participants,
    ):
        result = {}
        base_time = timezone.now()

        for item in EVENTS:
            sport = sports[item["sport"]]
            competition = competitions[item["competition"]]

            starts_at = (
                base_time
                + timedelta(
                    days=item["days"],
                )
            ).replace(
                hour=16,
                minute=0,
                second=0,
                microsecond=0,
            )

            event, created = SportingEvent.objects.get_or_create(
                source_name=DEMO_SOURCE,
                source_reference=item["reference"],
                defaults={
                    "sport": sport,
                    "competition": (competition),
                    "event_type": (SportingEvent.EventType.MATCH),
                    "name": (f"{item['home']} vs " f"{item['away']}"),
                    "starts_at": starts_at,
                    "ends_at": (
                        starts_at
                        + timedelta(
                            hours=3,
                        )
                    ),
                    "status": (SportingEvent.Status.SCHEDULED),
                    "venue": item["venue"],
                    "country_code": "UG",
                    "is_verified": True,
                    "verified_at": (base_time),
                },
            )

            if created:
                home = participants[
                    (
                        item["sport"],
                        item["home"],
                    )
                ]
                away = participants[
                    (
                        item["sport"],
                        item["away"],
                    )
                ]

                EventParticipant.objects.create(
                    event=event,
                    participant=home,
                    role=(EventParticipant.Role.HOME),
                    position=1,
                )
                EventParticipant.objects.create(
                    event=event,
                    participant=away,
                    role=(EventParticipant.Role.AWAY),
                    position=2,
                )

                self.stdout.write(f"Created event: " f"{event.name}")

            result[item["reference"]] = event

        return result

    def _seed_templates(
        self,
        categories,
    ):
        result = {}

        for item in TEMPLATES:
            template, created = MarketTemplate.objects.get_or_create(
                code=item["code"],
                defaults={
                    "category": categories[item["category"]],
                    "scope_type": item["scope_type"],
                    "name": item["name"],
                    "question_template": (item["question_template"]),
                    "description": ("League OS staging " "market template."),
                    "rules_template": (
                        "Resolve using the " "verified official " "competition result."
                    ),
                    "default_yes_label": ("Yes"),
                    "default_no_label": ("No"),
                    "is_active": True,
                },
            )

            result[item["category"]] = template

            if created:
                self.stdout.write(f"Created template: " f"{template.name}")

        return result

    def _seed_event_markets(
        self,
        *,
        creator,
        events,
        categories,
        templates,
    ):
        created_count = 0
        now = timezone.now()

        for item in MARKETS:
            event = events[item["event"]]
            category = categories[item["category"]]

            existing = Market.objects.filter(
                sporting_event=event,
                category=category,
                question=item["question"],
            ).first()

            if existing is not None:
                continue

            closes_at = event.starts_at - timedelta(
                minutes=15,
            )

            market = MarketCatalogService.create_market(
                sport=event.sport,
                category=category,
                template=templates.get(
                    item["category"],
                ),
                scope_type=(MarketScope.EVENT),
                sporting_event=event,
                question=item["question"],
                description=("League OS staging " "prediction market."),
                rules=(
                    "Resolve using the " "verified official result " "for the referenced event."
                ),
                resolution_source=("Official competition " "result"),
                resolution_criteria=("Use the verified final " "event record in League OS."),
                opens_at=(
                    now
                    - timedelta(
                        hours=1,
                    )
                ),
                closes_at=closes_at,
                is_featured=item["featured"],
                created_by=creator,
                yes_label=item["yes"],
                no_label=item["no"],
            )

            self._open_market(
                market=market,
                creator=creator,
            )

            created_count += 1

            self.stdout.write(f"Created OPEN market: " f"{market.question}")

        return created_count

    def _seed_long_horizon_markets(
        self,
        *,
        creator,
        competitions,
        participants,
        categories,
        templates,
    ):
        now = timezone.now()
        created_count = 0

        specs = [
            {
                "sport": "FOOTBALL",
                "scope": MarketScope.COMPETITION,
                "competition": ("Uganda Premier League"),
                "participant": None,
                "category": ("Tournament / Season"),
                "question": ("Will Vipers SC win the " "Uganda Premier League?"),
                "yes": "Vipers SC win the title",
                "no": "Any other club wins",
            },
            {
                "sport": "RUGBY",
                "scope": MarketScope.COMPETITION,
                "competition": ("Nile Special Rugby " "Premiership"),
                "participant": None,
                "category": ("Tournament / Season"),
                "question": ("Will KOBS Rugby Club win " "the Nile Special Rugby " "Premiership?"),
                "yes": "KOBS win the title",
                "no": "Any other club wins",
            },
            {
                "sport": "BASKETBALL",
                "scope": MarketScope.COMPETITION,
                "competition": ("National Basketball " "League Uganda"),
                "participant": None,
                "category": ("Tournament / Season"),
                "question": ("Will City Oilers win the " "National Basketball League?"),
                "yes": "City Oilers win",
                "no": "Any other team wins",
            },
            {
                "sport": "RUGBY",
                "scope": MarketScope.PARTICIPANT,
                "competition": None,
                "participant": ("KOBS Rugby Club"),
                "category": ("Player / Team Prop"),
                "question": (
                    "Will KOBS Rugby Club score " "3 or more tries in their " "next league match?"
                ),
                "yes": "3 or more tries",
                "no": "Fewer than 3 tries",
            },
        ]

        sports = {
            sport.code: sport
            for sport in Sport.objects.filter(code__in={item["sport"] for item in specs})
        }

        for item in specs:
            category = categories[item["category"]]
            competition = None
            participant = None

            if item["competition"]:
                competition = competitions[item["competition"]]

            if item["participant"]:
                participant = participants[
                    (
                        item["sport"],
                        item["participant"],
                    )
                ]

            query = {
                "category": category,
                "question": item["question"],
            }

            if competition is not None:
                query["competition"] = competition

            if participant is not None:
                query["participant"] = participant

            if Market.objects.filter(**query).exists():
                continue

            market = MarketCatalogService.create_market(
                sport=sports[item["sport"]],
                category=category,
                template=templates[item["category"]],
                scope_type=item["scope"],
                competition=competition,
                participant=participant,
                question=item["question"],
                description=("League OS staging " "long-horizon market."),
                rules=("Resolve from the verified " "official competition " "record."),
                resolution_source=("Official competition " "result"),
                resolution_criteria=("Use the verified official " "League OS result record."),
                opens_at=(
                    now
                    - timedelta(
                        hours=1,
                    )
                ),
                closes_at=(
                    now
                    + timedelta(
                        days=30,
                    )
                ),
                is_featured=False,
                created_by=creator,
                yes_label=item["yes"],
                no_label=item["no"],
            )

            self._open_market(
                market=market,
                creator=creator,
            )

            created_count += 1

            self.stdout.write(f"Created OPEN market: " f"{market.question}")

        return created_count

    @staticmethod
    def _open_market(
        *,
        market,
        creator,
    ):
        market = MarketLifecycleService.submit(
            market_id=market.id,
            actor=creator,
            notes=("Staging demo market ready " "for publication."),
        )

        market = MarketLifecycleService.approve(
            market_id=market.id,
            actor=creator,
            notes=("Staging demo market approved."),
        )

        MarketLifecycleService.open(
            market_id=market.id,
            actor=creator,
            notes=("Staging demo market opened."),
        )
