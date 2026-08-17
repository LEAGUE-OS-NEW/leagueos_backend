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
