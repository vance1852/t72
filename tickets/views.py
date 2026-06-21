from collections import Counter
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Audience,
    IDBlacklist,
    LimitInterceptStat,
    Performance,
    PurchaseLimitRule,
    RiskLog,
    Show,
    Ticket,
    TicketOrder,
)
from .serializers import (
    AudienceSerializer,
    IDBlacklistSerializer,
    LoginSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    PerformanceSerializer,
    PurchaseLimitRuleSerializer,
    RiskLogSerializer,
    ShowSerializer,
)

DEFAULT_MAX_PER_ID = 2
DEFAULT_MAX_PER_ACCOUNT = 4
RISK_ID_COUNT_THRESHOLD = 10
CONSECUTIVE_FAIL_WINDOW_MINUTES = 10
CONSECUTIVE_FAIL_THRESHOLD = 3


def _increment_stat(performance, intercept_type):
    stat, _ = LimitInterceptStat.objects.get_or_create(
        performance=performance, intercept_type=intercept_type,
        defaults={"count": 0},
    )
    LimitInterceptStat.objects.filter(pk=stat.pk).update(count=F("count") + 1)


def _check_consecutive_fail(user, performance):
    """短时间连续下单失败检测。返回 (是否触发, 描述)。"""
    if not user or not user.is_authenticated:
        return False, ""
    window_start = timezone.now() - timedelta(minutes=CONSECUTIVE_FAIL_WINDOW_MINUTES)
    recent_failures = RiskLog.objects.filter(
        user=user,
        performance=performance,
        risk_type="consecutive_fail",
        created_at__gte=window_start,
    ).count()
    if recent_failures >= CONSECUTIVE_FAIL_THRESHOLD - 1:
        return True, f"{CONSECUTIVE_FAIL_WINDOW_MINUTES}分钟内连续下单失败{recent_failures + 1}次"
    return False, ""


def _check_too_many_ids(user):
    """账号绑定证件数超阈值检测。返回 (是否触发, 描述)。"""
    if not user or not user.is_authenticated:
        return False, ""
    id_count = Audience.objects.filter(user=user).values("id_type", "id_number").distinct().count()
    if id_count > RISK_ID_COUNT_THRESHOLD:
        return True, f"账号已绑定{id_count}个证件，超过阈值{RISK_ID_COUNT_THRESHOLD}"
    return False, ""


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(username=s.validated_data["username"], password=s.validated_data["password"])
        if user is None:
            return Response({"detail": "用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED)
        token = RefreshToken.for_user(user)
        return Response({"access_token": str(token.access_token), "token_type": "bearer"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    return Response({"id": u.id, "username": u.username, "display_name": u.get_full_name() or "平台管理员"})


class ShowViewSet(viewsets.ModelViewSet):
    queryset = Show.objects.all().order_by("id")
    serializer_class = ShowSerializer


class PerformanceViewSet(viewsets.ModelViewSet):
    queryset = Performance.objects.select_related("show").all().order_by("start_at")
    serializer_class = PerformanceSerializer

    @action(detail=True, methods=["get"], url_path="risk-stats")
    def risk_stats(self, request, pk=None):
        perf = self.get_object()
        stats = LimitInterceptStat.objects.filter(performance=perf)
        stats_map = {s.intercept_type: s.count for s in stats}
        risk_count = RiskLog.objects.filter(performance=perf).count()
        return Response({
            "performance": perf.id,
            "limit_id_intercepts": stats_map.get("id", 0),
            "limit_account_intercepts": stats_map.get("account", 0),
            "blacklist_intercepts": stats_map.get("blacklist", 0),
            "risk_log_count": risk_count,
        })


class AudienceViewSet(viewsets.ModelViewSet):
    """实名观演人管理。归属当前登录账号。"""
    serializer_class = AudienceSerializer

    def get_queryset(self):
        return Audience.objects.filter(user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PurchaseLimitRuleViewSet(viewsets.ModelViewSet):
    """场次限购规则配置。"""
    queryset = PurchaseLimitRule.objects.select_related("performance").all()
    serializer_class = PurchaseLimitRuleSerializer
    http_method_names = ["get", "post", "put", "patch"]

    def get_object(self):
        perf_id = self.kwargs.get("pk")
        rule, _ = PurchaseLimitRule.objects.get_or_create(
            performance_id=perf_id,
            defaults={"max_per_id": DEFAULT_MAX_PER_ID, "max_per_account": DEFAULT_MAX_PER_ACCOUNT},
        )
        return rule


class IDBlacklistViewSet(viewsets.ModelViewSet):
    """证件黑名单管理。"""
    queryset = IDBlacklist.objects.all().order_by("-created_at")
    serializer_class = IDBlacklistSerializer


class RiskLogViewSet(viewsets.ReadOnlyModelViewSet):
    """风险日志（只读）。"""
    queryset = RiskLog.objects.select_related("user", "performance", "performance__show").all()
    serializer_class = RiskLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        perf = self.request.query_params.get("performance")
        rtype = self.request.query_params.get("risk_type")
        if perf:
            qs = qs.filter(performance_id=perf)
        if rtype:
            qs = qs.filter(risk_type=rtype)
        return qs


class OrderViewSet(viewsets.ModelViewSet):
    queryset = TicketOrder.objects.select_related(
        "performance", "performance__show", "user"
    ).prefetch_related("tickets", "tickets__audience").all().order_by("-id")
    http_method_names = ["get", "post"]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        s = OrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        user = request.user if request.user.is_authenticated else None
        warnings = []

        try:
            perf = Performance.objects.select_related("show").get(pk=data["performance"])
        except Performance.DoesNotExist:
            return Response({"detail": "场次不存在"}, status=status.HTTP_404_NOT_FOUND)

        quantity = len(data["audience_ids"])
        remaining = perf.total_seats - perf.sold_seats
        if quantity > remaining:
            return Response({"detail": "余票不足"}, status=status.HTTP_409_CONFLICT)

        audiences = Audience.objects.filter(
            id__in=data["audience_ids"]
        ).select_for_update()
        if audiences.count() != quantity:
            return Response({"detail": "存在无效的观演人"}, status=status.HTTP_400_BAD_REQUEST)

        if user:
            for aud in audiences:
                if aud.user_id != user.id:
                    return Response(
                        {"detail": f"观演人「{aud.name}」不属于当前账号"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        rule = getattr(perf, "limit_rule", None)
        max_per_id = rule.max_per_id if rule else DEFAULT_MAX_PER_ID
        max_per_account = rule.max_per_account if rule else DEFAULT_MAX_PER_ACCOUNT

        id_counts_request = Counter()
        for aud in audiences:
            id_counts_request[(aud.id_type, aud.id_number)] += 1

        for (id_type, id_number), cnt in id_counts_request.items():
            if cnt > max_per_id:
                RiskLog.objects.create(
                    user=user, performance=perf, risk_type="limit_id",
                    id_number=id_number,
                    description=f"同证件在本单中购票{cnt}张，超过上限{max_per_id}",
                )
                _increment_stat(perf, "id")
                return Response(
                    {"detail": f"证件号 {id_number} 在本单中超过限购上限 {max_per_id} 张"},
                    status=status.HTTP_409_CONFLICT,
                )

        paid_orders = TicketOrder.objects.filter(
            performance=perf, status="paid"
        ).values_list("id", flat=True)

        for (id_type, id_number), cnt_request in id_counts_request.items():
            existing = Ticket.objects.filter(
                performance=perf,
                order_id__in=paid_orders,
                audience__id_type=id_type,
                audience__id_number=id_number,
            ).count()
            if existing + cnt_request > max_per_id:
                RiskLog.objects.create(
                    user=user, performance=perf, risk_type="limit_id",
                    id_number=id_number,
                    description=f"证件已购{existing}张+本单{cnt_request}张，超过上限{max_per_id}",
                )
                _increment_stat(perf, "id")
                return Response(
                    {"detail": f"证件号 {id_number} 在本场次累计超过限购上限 {max_per_id} 张"},
                    status=status.HTTP_409_CONFLICT,
                )

        if user:
            account_existing = Ticket.objects.filter(
                performance=perf,
                order_id__in=paid_orders,
                order__user=user,
            ).count()
            if account_existing + quantity > max_per_account:
                RiskLog.objects.create(
                    user=user, performance=perf, risk_type="limit_account",
                    description=f"账号已购{account_existing}张+本单{quantity}张，超过上限{max_per_account}",
                )
                _increment_stat(perf, "account")
                return Response(
                    {"detail": f"当前账号在本场次累计超过限购上限 {max_per_account} 张"},
                    status=status.HTTP_409_CONFLICT,
                )

        blacklist_ids = set(
            IDBlacklist.objects.values_list("id_type", "id_number")
        )
        for aud in audiences:
            if (aud.id_type, aud.id_number) in blacklist_ids:
                RiskLog.objects.create(
                    user=user, performance=perf, risk_type="id_blacklist",
                    id_number=aud.id_number,
                    description=f"黑名单证件号 {aud.id_number} 尝试下单",
                )
                _increment_stat(perf, "blacklist")
                return Response(
                    {"detail": f"证件号 {aud.id_number} 已被列入黑名单，无法购票"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        triggered, desc = _check_too_many_ids(user)
        if triggered:
            RiskLog.objects.create(
                user=user, performance=perf, risk_type="too_many_ids", description=desc,
            )
            warnings.append(desc)

        order = TicketOrder.objects.create(
            performance=perf,
            user=user,
            customer_name=data["customer_name"],
            phone=data.get("phone", ""),
            quantity=quantity,
            amount=perf.price * quantity,
            status="paid",
        )
        for aud in audiences:
            Ticket.objects.create(
                order=order, performance=perf, audience=aud,
            )
        perf.sold_seats += quantity
        perf.save(update_fields=["sold_seats"])

        resp_data = OrderSerializer(order).data
        if warnings:
            resp_data["risk_warnings"] = warnings
        return Response(resp_data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    show_total = Show.objects.count()
    show_on_sale = Show.objects.filter(status="on_sale").count()
    perf_total = Performance.objects.count()
    order_paid = TicketOrder.objects.filter(status="paid").count()
    sold = sum(p.sold_seats for p in Performance.objects.all())
    capacity = sum(p.total_seats for p in Performance.objects.all())
    blacklist_count = IDBlacklist.objects.count()
    risk_count = RiskLog.objects.count()
    return Response({
        "show_total": show_total,
        "show_on_sale": show_on_sale,
        "performance_total": perf_total,
        "order_paid": order_paid,
        "seats_sold": sold,
        "seats_capacity": capacity,
        "blacklist_count": blacklist_count,
        "risk_log_count": risk_count,
    })
