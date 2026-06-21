"""初始化内置管理员与种子业务数据（幂等）。"""
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

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


class Command(BaseCommand):
    help = "初始化管理员与演出票务种子数据"

    def handle(self, *args, **options):
        username = settings.DEFAULT_ADMIN_USERNAME
        password = settings.DEFAULT_ADMIN_PASSWORD
        admin, _created = User.objects.get_or_create(
            username=username,
            defaults={"is_superuser": True, "is_staff": True, "first_name": "平台管理员"},
        )
        if _created:
            admin.set_password(password)
            admin.save()
            self.stdout.write("已创建管理员账号")

        if Show.objects.exists():
            self.stdout.write("业务数据已存在，跳过")
            return

        shows = [
            Show.objects.create(title="星河巡回演唱会", troupe="星河乐团", genre="concert", status="on_sale"),
            Show.objects.create(title="金陵往事话剧", troupe="城南剧社", genre="drama", status="on_sale"),
            Show.objects.create(title="敦煌音乐剧", troupe="丝路艺术团", genre="musical", status="upcoming"),
            Show.objects.create(title="经典戏曲专场", troupe="梨园名家", genre="opera", status="ended"),
        ]

        now = datetime.now().replace(microsecond=0)
        perfs = [
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=3), total_seats=1200, sold_seats=860, price=380),
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=4), total_seats=1200, sold_seats=300, price=380),
            Performance.objects.create(show=shows[1], hall="小剧场", start_at=now + timedelta(days=2), total_seats=300, sold_seats=290, price=180),
            Performance.objects.create(show=shows[2], hall="大剧院", start_at=now + timedelta(days=20), total_seats=900, sold_seats=0, price=280),
        ]

        PurchaseLimitRule.objects.create(performance=perfs[0], max_per_id=2, max_per_account=4)
        PurchaseLimitRule.objects.create(performance=perfs[1], max_per_id=2, max_per_account=4)
        PurchaseLimitRule.objects.create(performance=perfs[2], max_per_id=4, max_per_account=6)

        audiences = [
            Audience.objects.create(user=admin, name="陈静", id_type="id_card", id_number="310101199001011234"),
            Audience.objects.create(user=admin, name="刘洋", id_type="id_card", id_number="310101199102022345"),
            Audience.objects.create(user=admin, name="孙琳", id_type="id_card", id_number="310101199203033456"),
            Audience.objects.create(user=admin, name="王磊", id_type="id_card", id_number="310101199304044567"),
            Audience.objects.create(user=admin, name="赵雪", id_type="passport", id_number="E12345678"),
        ]

        order1 = TicketOrder.objects.create(
            performance=perfs[0], user=admin, customer_name="陈静", phone="13900001111",
            quantity=2, amount=760, status="paid",
        )
        Ticket.objects.create(order=order1, performance=perfs[0], audience=audiences[0])
        Ticket.objects.create(order=order1, performance=perfs[0], audience=audiences[2])

        order2 = TicketOrder.objects.create(
            performance=perfs[2], user=admin, customer_name="刘洋", phone="13900002222",
            quantity=4, amount=720, status="paid",
        )
        Ticket.objects.create(order=order2, performance=perfs[2], audience=audiences[1])
        Ticket.objects.create(order=order2, performance=perfs[2], audience=audiences[3])
        Ticket.objects.create(order=order2, performance=perfs[2], audience=audiences[4])
        Ticket.objects.create(order=order2, performance=perfs[2], audience=audiences[0])

        order3 = TicketOrder.objects.create(
            performance=perfs[0], user=admin, customer_name="孙琳", phone="13900003333",
            quantity=1, amount=380, status="cancelled",
        )
        Ticket.objects.create(order=order3, performance=perfs[0], audience=audiences[2])

        IDBlacklist.objects.create(
            id_type="id_card", id_number="310101198808088888",
            reason="黄牛倒票行为",
        )
        IDBlacklist.objects.create(
            id_type="id_card", id_number="310101197707077777",
            reason="多次违规退票",
        )

        RiskLog.objects.create(
            user=admin, performance=perfs[0], risk_type="limit_id",
            id_number="310101199001011234",
            description="证件在本场次累计超过限购上限",
        )
        RiskLog.objects.create(
            user=admin, performance=perfs[2], risk_type="id_blacklist",
            id_number="310101198808088888",
            description="黑名单证件号尝试下单",
        )

        LimitInterceptStat.objects.create(performance=perfs[0], intercept_type="id", count=2)
        LimitInterceptStat.objects.create(performance=perfs[0], intercept_type="account", count=1)
        LimitInterceptStat.objects.create(performance=perfs[2], intercept_type="blacklist", count=1)

        self.stdout.write("种子数据初始化完成")
