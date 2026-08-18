from rest_framework import serializers


class HealthCheckDependenciesSerializer(serializers.Serializer):
    database = serializers.BooleanField()
    cache = serializers.BooleanField()


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    dependencies = HealthCheckDependenciesSerializer()


class PesapalDiagnosticAuthenticationSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    error_type = serializers.CharField(allow_blank=True)


class PesapalDiagnosticAddressSerializer(serializers.Serializer):
    family = serializers.CharField()
    address = serializers.CharField()


class PesapalDiagnosticDnsSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    elapsed_ms = serializers.FloatField(
        allow_null=True,
    )
    addresses = PesapalDiagnosticAddressSerializer(
        many=True,
    )
    error_type = serializers.CharField(
        allow_blank=True,
    )


class PesapalDiagnosticTcpSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    elapsed_ms = serializers.FloatField(
        allow_null=True,
    )
    error_type = serializers.CharField(
        allow_blank=True,
    )


class PesapalDiagnosticTlsSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    elapsed_ms = serializers.FloatField(
        allow_null=True,
    )
    protocol = serializers.CharField(
        allow_blank=True,
    )
    error_type = serializers.CharField(
        allow_blank=True,
    )


class PesapalDiagnosticProbeSerializer(serializers.Serializer):
    family = serializers.CharField()
    address = serializers.CharField()
    tcp = PesapalDiagnosticTcpSerializer()
    tls = PesapalDiagnosticTlsSerializer()


class PesapalDirectHttpAuthSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    elapsed_ms = serializers.FloatField(
        allow_null=True,
    )
    http_status = serializers.IntegerField(
        allow_null=True,
    )
    token_present = serializers.BooleanField()
    error_type = serializers.CharField(
        allow_blank=True,
    )


class PesapalDiagnosticTransportSerializer(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField()
    dns = PesapalDiagnosticDnsSerializer()
    probes = PesapalDiagnosticProbeSerializer(
        many=True,
    )


class PesapalDiagnosticSerializer(serializers.Serializer):
    environment = serializers.CharField()
    sandbox = serializers.BooleanField()
    base_url = serializers.CharField()
    credentials_present = serializers.BooleanField()
    ipn_configured = serializers.BooleanField()
    callback_configured = serializers.BooleanField()
    transport = PesapalDiagnosticTransportSerializer(
        required=False,
    )
    direct_http_auth = PesapalDirectHttpAuthSerializer(
        required=False,
    )
    authentication = PesapalDiagnosticAuthenticationSerializer()


class MarketCatalogueAuditHistorySerializer(serializers.Serializer):
    order_count = serializers.IntegerField()
    fill_count = serializers.IntegerField()
    position_count = serializers.IntegerField()
    complete_set_issuance_count = serializers.IntegerField()
    collateral_entry_count = serializers.IntegerField()
    status_transition_count = serializers.IntegerField()
    watchlist_count = serializers.IntegerField()
    recent_view_count = serializers.IntegerField()
    has_liquidity_configuration = serializers.BooleanField()
    liquidity_status = serializers.CharField(
        allow_blank=True,
    )
    initial_liquidity_ugx = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        allow_null=True,
    )
    has_collateral_pool = serializers.BooleanField()
    locked_collateral = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        allow_null=True,
    )
    has_settlement = serializers.BooleanField()


class MarketCatalogueAuditRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    question = serializers.CharField()
    sport = serializers.CharField()
    category = serializers.CharField()
    status = serializers.CharField()
    is_featured = serializers.BooleanField()
    is_catalog_visible = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    classification = serializers.CharField()
    history = MarketCatalogueAuditHistorySerializer()


class MarketCatalogueCanonicalGroupSerializer(serializers.Serializer):
    question = serializers.CharField()
    candidate_count = serializers.IntegerField()
    candidate_ids = serializers.ListField(
        child=serializers.UUIDField(),
    )
    needs_keeper_selection = serializers.BooleanField()


class MarketCatalogueAuditSerializer(serializers.Serializer):
    canonical_questions = serializers.ListField(
        child=serializers.CharField(),
    )
    total_markets = serializers.IntegerField()
    summary = serializers.DictField(
        child=serializers.IntegerField(),
    )
    canonical_groups = MarketCatalogueCanonicalGroupSerializer(
        many=True,
    )
    rows = MarketCatalogueAuditRowSerializer(
        many=True,
    )
