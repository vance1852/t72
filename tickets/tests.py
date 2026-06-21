from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tickets.models import (
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


class TicketingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tester", password="tester123")
        cls.other_user = User.objects.create_user(username="other", password="other123")
        show = Show.objects.create(title="测试演唱会", genre="concert", status="on_sale")
        cls.perf = Performance.objects.create(
            show=show, hall="测试厅", start_at=timezone.now() + timedelta(days=3),
            total_seats=100, sold_seats=0, price=100,
        )
        PurchaseLimitRule.objects.create(
            performance=cls.perf, max_per_id=2, max_per_account=3,
        )
        cls.aud1 = Audience.objects.create(
            user=cls.user, name="张三", id_type="id_card", id_number="110101199001010001",
        )
        cls.aud2 = Audience.objects.create(
            user=cls.user, name="李四", id_type="id_card", id_number="110101199001010002",
        )
        cls.aud3 = Audience.objects.create(
            user=cls.user, name="王五", id_type="id_card", id_number="110101199001010003",
        )
        cls.black_aud = Audience.objects.create(
            user=cls.user, name="黑六", id_type="id_card", id_number="110101198001019999",
        )
        IDBlacklist.objects.create(
            id_type="id_card", id_number="110101198001019999", reason="黄牛",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _post_order(self, audience_ids, status_expected=201):
        resp = self.client.post("/api/orders", {
            "performance": self.perf.id,
            "customer_name": "测试客户",
            "phone": "13800000000",
            "audience_ids": audience_ids,
        }, format="json")
        self.assertEqual(resp.status_code, status_expected, resp.data)
        return resp

    def test_01_auth_login_and_me(self):
        client = APIClient()
        resp = client.post("/api/auth/login", {
            "username": "tester", "password": "tester123",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        token = resp.data["access_token"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        resp = client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["username"], "tester")

    def test_02_audience_crud(self):
        resp = self.client.get("/api/audiences")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 4)
        resp = self.client.post("/api/audiences", {
            "name": "赵七", "id_type": "passport", "id_number": "E99999999",
        }, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Audience.objects.filter(user=self.user).count(), 5)

    def test_03_purchase_limit_rule(self):
        resp = self.client.get(f"/api/purchase-limit-rules/{self.perf.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["max_per_id"], 2)
        self.assertEqual(resp.data["max_per_account"], 3)
        resp = self.client.put(f"/api/purchase-limit-rules/{self.perf.id}", {
            "performance": self.perf.id, "max_per_id": 1, "max_per_account": 2,
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.perf.refresh_from_db()
        self.assertEqual(self.perf.limit_rule.max_per_id, 1)
        PurchaseLimitRule.objects.filter(performance=self.perf).update(max_per_id=2, max_per_account=3)

    def test_04_realname_order_success(self):
        resp = self._post_order([self.aud1.id, self.aud2.id])
        self.assertEqual(resp.data["quantity"], 2)
        self.assertEqual(len(resp.data["tickets"]), 2)
        ticket_names = [t["audience"]["name"] for t in resp.data["tickets"]]
        self.assertIn("张三", ticket_names)
        self.assertIn("李四", ticket_names)
        self.perf.refresh_from_db()
        self.assertEqual(self.perf.sold_seats, 2)
        TicketOrder.objects.filter(performance=self.perf).delete()
        self.perf.sold_seats = 0
        self.perf.save()

    def test_05_id_limit_intercept(self):
        self._post_order([self.aud1.id])
        self._post_order([self.aud1.id])
        resp = self._post_order([self.aud1.id], status_expected=409)
        self.assertIn("证件号", resp.data["detail"])
        self.assertIn("超过限购上限", resp.data["detail"])
        stat = LimitInterceptStat.objects.get(
            performance=self.perf, intercept_type="id",
        )
        self.assertGreaterEqual(stat.count, 1)
        self.assertTrue(RiskLog.objects.filter(risk_type="limit_id").exists())
        TicketOrder.objects.filter(performance=self.perf).delete()
        self.perf.sold_seats = 0
        self.perf.save()
        LimitInterceptStat.objects.all().delete()
        RiskLog.objects.all().delete()

    def test_06_account_limit_intercept(self):
        self._post_order([self.aud1.id])
        self._post_order([self.aud2.id])
        self._post_order([self.aud3.id])
        aud4 = Audience.objects.create(
            user=self.user, name="测试六", id_type="id_card", id_number="110101199001010006",
        )
        resp = self._post_order([aud4.id], status_expected=409)
        self.assertIn("账号", resp.data["detail"])
        stat = LimitInterceptStat.objects.get(
            performance=self.perf, intercept_type="account",
        )
        self.assertGreaterEqual(stat.count, 1)
        self.assertTrue(RiskLog.objects.filter(risk_type="limit_account").exists())
        TicketOrder.objects.filter(performance=self.perf).delete()
        self.perf.sold_seats = 0
        self.perf.save()
        LimitInterceptStat.objects.all().delete()
        RiskLog.objects.all().delete()

    def test_07_blacklist_intercept(self):
        resp = self._post_order([self.black_aud.id], status_expected=403)
        self.assertIn("黑名单", resp.data["detail"])
        stat = LimitInterceptStat.objects.get(
            performance=self.perf, intercept_type="blacklist",
        )
        self.assertEqual(stat.count, 1)
        self.assertTrue(RiskLog.objects.filter(risk_type="id_blacklist").exists())
        RiskLog.objects.all().delete()
        LimitInterceptStat.objects.all().delete()

    def test_08_cancel_then_repurchase(self):
        order_resp = self._post_order([self.aud1.id, self.aud2.id])
        order_id = order_resp.data["id"]
        self.perf.refresh_from_db()
        self.assertEqual(self.perf.sold_seats, 2)
        paid_count = Ticket.objects.filter(
            performance=self.perf, order__status="paid",
            audience__id_number=self.aud1.id_number,
        ).count()
        self.assertEqual(paid_count, 1)

        cancel_resp = self.client.post(f"/api/orders/{order_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.data["status"], "cancelled")
        self.perf.refresh_from_db()
        self.assertEqual(self.perf.sold_seats, 0)

        paid_count_after = Ticket.objects.filter(
            performance=self.perf, order__status="paid",
            audience__id_number=self.aud1.id_number,
        ).count()
        self.assertEqual(paid_count_after, 0)

        self._post_order([self.aud1.id, self.aud2.id])
        self.perf.refresh_from_db()
        self.assertEqual(self.perf.sold_seats, 2)

        TicketOrder.objects.filter(performance=self.perf).delete()
        self.perf.sold_seats = 0
        self.perf.save()
        RiskLog.objects.all().delete()
        LimitInterceptStat.objects.all().delete()

    def test_09_consecutive_fail_records(self):
        for _ in range(3):
            self._post_order([self.black_aud.id], status_expected=403)
        fail_count = RiskLog.objects.filter(
            user=self.user, performance=self.perf, risk_type="consecutive_fail",
        ).count()
        self.assertGreaterEqual(fail_count, 3)
        resp = self._post_order([self.aud1.id], status_expected=429)
        self.assertIn("连续下单失败", resp.data["detail"])
        TicketOrder.objects.filter(performance=self.perf).delete()
        self.perf.sold_seats = 0
        self.perf.save()
        RiskLog.objects.all().delete()
        LimitInterceptStat.objects.all().delete()

    def test_10_performance_risk_stats(self):
        LimitInterceptStat.objects.create(
            performance=self.perf, intercept_type="id", count=5,
        )
        LimitInterceptStat.objects.create(
            performance=self.perf, intercept_type="account", count=2,
        )
        LimitInterceptStat.objects.create(
            performance=self.perf, intercept_type="blacklist", count=1,
        )
        RiskLog.objects.create(user=self.user, performance=self.perf, risk_type="limit_id")
        RiskLog.objects.create(user=self.user, performance=self.perf, risk_type="id_blacklist")
        resp = self.client.get(f"/api/performances/{self.perf.id}/risk-stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["limit_id_intercepts"], 5)
        self.assertEqual(resp.data["limit_account_intercepts"], 2)
        self.assertEqual(resp.data["blacklist_intercepts"], 1)
        self.assertEqual(resp.data["risk_log_count"], 2)

    def test_11_audience_belongs_to_user(self):
        other_client = APIClient()
        other_client.force_authenticate(user=self.other_user)
        resp = other_client.post("/api/orders", {
            "performance": self.perf.id,
            "customer_name": "越权",
            "audience_ids": [self.aud1.id],
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不属于当前账号", resp.data["detail"])

    def test_12_dashboard_stats(self):
        resp = self.client.get("/api/dashboard/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("blacklist_count", resp.data)
        self.assertIn("risk_log_count", resp.data)
        self.assertEqual(resp.data["blacklist_count"], 1)

    def test_13_risk_log_list_and_filter(self):
        RiskLog.objects.create(user=self.user, performance=self.perf, risk_type="limit_id", description="a")
        RiskLog.objects.create(user=self.user, performance=self.perf, risk_type="id_blacklist", description="b")
        RiskLog.objects.create(user=self.other_user, risk_type="too_many_ids", description="c")
        resp = self.client.get("/api/risk-logs")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data), 3)
        resp = self.client.get(f"/api/risk-logs?performance={self.perf.id}")
        self.assertEqual(len(resp.data), 2)
        resp = self.client.get("/api/risk-logs?risk_type=too_many_ids")
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["risk_type"], "too_many_ids")

    def test_14_id_blacklist_crud(self):
        resp = self.client.get("/api/id-blacklist")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        resp = self.client.post("/api/id-blacklist", {
            "id_type": "id_card", "id_number": "110101197001017777", "reason": "测试拉黑",
        }, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(IDBlacklist.objects.count(), 2)
        resp = self.client.delete(f"/api/id-blacklist/{resp.data['id']}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(IDBlacklist.objects.count(), 1)
