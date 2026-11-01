from rest_framework import serializers


class PlanRequestSerializer(serializers.Serializer):
    """The API accepts human-readable U.S. place names or postal addresses."""

    start = serializers.CharField(max_length=200, trim_whitespace=True)
    finish = serializers.CharField(max_length=200, trim_whitespace=True)

    def validate_start(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Enter a starting U.S. location.")
        return value.strip()

    def validate_finish(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Enter a destination U.S. location.")
        return value.strip()
