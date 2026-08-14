from rest_framework import serializers


class HealthCheckDependenciesSerializer(serializers.Serializer):
    database = serializers.BooleanField()
    cache = serializers.BooleanField()


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    dependencies = HealthCheckDependenciesSerializer()
