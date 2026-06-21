from django.conf import settings
from django.db import models


class Show(models.Model):
    """演出剧目。"""

    GENRE_CHOICES = [
        ("concert", "演唱会"),
        ("drama", "话剧"),
        ("musical", "音乐剧"),
        ("opera", "戏曲"),
        ("other", "其他"),
    ]
    STATUS_CHOICES = [
        ("on_sale", "售票中"),
        ("upcoming", "待开票"),
        ("ended", "已结束"),
    ]

    title = models.CharField(max_length=128)
    troupe = models.CharField(max_length=128, blank=True, default="")
    genre = models.CharField(max_length=16, choices=GENRE_CHOICES, default="concert")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="upcoming")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shows"


class Performance(models.Model):
    """场次。"""

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="performances")
    hall = models.CharField(max_length=64, default="")
    start_at = models.DateTimeField()
    total_seats = models.IntegerField(default=0)
    sold_seats = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "performances"


class PurchaseLimitRule(models.Model):
    """场次限购规则。未配置时走默认值。"""

    performance = models.OneToOneField(
        Performance, on_delete=models.CASCADE, related_name="limit_rule", primary_key=True
    )
    max_per_id = models.IntegerField(default=2, help_text="同一证件同场次最多购买数 N")
    max_per_account = models.IntegerField(default=4, help_text="同一账号同场次最多购买数 M")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "purchase_limit_rules"


class Audience(models.Model):
    """实名观演人，归属到账号。"""

    ID_TYPE_CHOICES = [
        ("id_card", "身份证"),
        ("passport", "护照"),
        ("hk_macau", "港澳通行证"),
        ("taiwan", "台湾通行证"),
        ("other", "其他"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="audiences"
    )
    name = models.CharField(max_length=64)
    id_type = models.CharField(max_length=16, choices=ID_TYPE_CHOICES, default="id_card")
    id_number = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audiences"
        unique_together = [("user", "id_type", "id_number")]


class IDBlacklist(models.Model):
    """证件号黑名单。"""

    id_type = models.CharField(max_length=16, choices=Audience.ID_TYPE_CHOICES, default="id_card")
    id_number = models.CharField(max_length=64, unique=True)
    reason = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "id_blacklist"


class TicketOrder(models.Model):
    """购票订单。"""

    STATUS_CHOICES = [
        ("paid", "已支付"),
        ("cancelled", "已取消"),
    ]

    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="orders")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders", null=True, blank=True
    )
    customer_name = models.CharField(max_length=64)
    phone = models.CharField(max_length=32, blank=True, default="")
    quantity = models.IntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="paid")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_orders"


class Ticket(models.Model):
    """单张票，绑定一个观演人。"""

    order = models.ForeignKey(TicketOrder, on_delete=models.CASCADE, related_name="tickets")
    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="tickets")
    audience = models.ForeignKey(
        Audience, on_delete=models.PROTECT, related_name="tickets"
    )
    seat_no = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets"


class RiskLog(models.Model):
    """风险日志。"""

    RISK_TYPE_CHOICES = [
        ("consecutive_fail", "短时间连续下单失败"),
        ("too_many_ids", "账号绑定证件数超阈值"),
        ("id_blacklist", "黑名单证件下单"),
        ("limit_id", "证件超限购"),
        ("limit_account", "账号超限购"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_logs", null=True, blank=True
    )
    performance = models.ForeignKey(
        Performance, on_delete=models.CASCADE, related_name="risk_logs", null=True, blank=True
    )
    risk_type = models.CharField(max_length=32, choices=RISK_TYPE_CHOICES)
    id_number = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_logs"
        ordering = ["-created_at"]


class LimitInterceptStat(models.Model):
    """场次限购拦截计数（每次拦截自增，便于统计）。"""

    performance = models.ForeignKey(
        Performance, on_delete=models.CASCADE, related_name="limit_stats"
    )
    intercept_type = models.CharField(
        max_length=16,
        choices=[
            ("id", "证件超限购"),
            ("account", "账号超限购"),
            ("blacklist", "黑名单拦截"),
        ],
    )
    count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "limit_intercept_stats"
        unique_together = [("performance", "intercept_type")]
