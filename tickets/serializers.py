from rest_framework import serializers

from .models import (
    Audience,
    IDBlacklist,
    Performance,
    PurchaseLimitRule,
    RiskLog,
    Show,
    Ticket,
    TicketOrder,
)


class ShowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Show
        fields = ["id", "title", "troupe", "genre", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


class PerformanceSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="show.title", read_only=True)
    remaining_seats = serializers.SerializerMethodField()
    max_per_id = serializers.SerializerMethodField()
    max_per_account = serializers.SerializerMethodField()

    class Meta:
        model = Performance
        fields = [
            "id", "show", "show_title", "hall", "start_at",
            "total_seats", "sold_seats", "remaining_seats", "price", "created_at",
            "max_per_id", "max_per_account",
        ]
        read_only_fields = ["id", "sold_seats", "created_at"]

    def get_remaining_seats(self, obj):
        return obj.total_seats - obj.sold_seats

    def get_max_per_id(self, obj):
        rule = getattr(obj, "limit_rule", None)
        return rule.max_per_id if rule else 2

    def get_max_per_account(self, obj):
        rule = getattr(obj, "limit_rule", None)
        return rule.max_per_account if rule else 4


class PurchaseLimitRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseLimitRule
        fields = ["performance", "max_per_id", "max_per_account", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_max_per_id(self, value):
        if value < 1:
            raise serializers.ValidationError("证件限购数至少为 1")
        return value

    def validate_max_per_account(self, value):
        if value < 1:
            raise serializers.ValidationError("账号限购数至少为 1")
        return value


class AudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Audience
        fields = ["id", "name", "id_type", "id_number", "created_at"]
        read_only_fields = ["id", "created_at"]


class IDBlacklistSerializer(serializers.ModelSerializer):
    class Meta:
        model = IDBlacklist
        fields = ["id", "id_type", "id_number", "reason", "created_at"]
        read_only_fields = ["id", "created_at"]


class TicketSerializer(serializers.ModelSerializer):
    audience = AudienceSerializer(read_only=True)
    audience_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "audience", "audience_id", "seat_no", "created_at"]
        read_only_fields = ["id", "created_at"]


class OrderSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="performance.show.title", read_only=True)
    tickets = TicketSerializer(many=True, read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = TicketOrder
        fields = [
            "id", "performance", "show_title", "username",
            "customer_name", "phone", "quantity", "amount", "status", "created_at",
            "tickets",
        ]
        read_only_fields = ["id", "amount", "status", "created_at", "tickets"]


class OrderCreateSerializer(serializers.Serializer):
    performance = serializers.IntegerField()
    customer_name = serializers.CharField(max_length=64)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    audience_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    def validate_audience_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("同订单不能重复使用相同观演人")
        if len(value) < 1:
            raise serializers.ValidationError("至少选择一个观演人")
        return value


class RiskLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")
    performance_title = serializers.SerializerMethodField()
    risk_type_display = serializers.CharField(source="get_risk_type_display", read_only=True)

    class Meta:
        model = RiskLog
        fields = [
            "id", "username", "performance", "performance_title",
            "risk_type", "risk_type_display", "id_number", "description", "created_at",
        ]
        read_only_fields = fields

    def get_performance_title(self, obj):
        if not obj.performance:
            return ""
        return f"{obj.performance.show.title} - {obj.performance.hall}"


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
