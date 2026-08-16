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


class PesapalDiagnosticSerializer(serializers.Serializer):
    environment = serializers.CharField()
    sandbox = serializers.BooleanField()
    base_url = serializers.CharField()
    credentials_present = serializers.BooleanField()
    ipn_configured = serializers.BooleanField()
    callback_configured = serializers.BooleanField()
    authentication = PesapalDiagnosticAuthenticationSerializer()
