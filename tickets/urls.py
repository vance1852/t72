from django.http import JsonResponse
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AudienceViewSet,
    IDBlacklistViewSet,
    LoginView,
    OrderViewSet,
    PerformanceViewSet,
    PurchaseLimitRuleViewSet,
    RiskLogViewSet,
    ShowViewSet,
    dashboard_stats,
    me,
)


def health(_request):
    return JsonResponse({"status": "ok", "service": "show-ticketing-admin"})


router = DefaultRouter(trailing_slash=False)
router.register("shows", ShowViewSet)
router.register("performances", PerformanceViewSet)
router.register("orders", OrderViewSet)
router.register("audiences", AudienceViewSet, basename="audience")
router.register("purchase-limit-rules", PurchaseLimitRuleViewSet, basename="purchaselimitrule")
router.register("id-blacklist", IDBlacklistViewSet, basename="idblacklist")
router.register("risk-logs", RiskLogViewSet, basename="risklog")

urlpatterns = [
    path("health", health),
    path("auth/login", LoginView.as_view()),
    path("auth/me", me),
    path("dashboard/stats", dashboard_stats),
]

urlpatterns += router.urls
