from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.barbershop_catalog import (
    BUSINESS_HOURS_CATALOG,
    FULL_ADDRESS,
    GOOGLE_MAPS_URL,
    PAYMENT_METHODS,
    PROMOTION,
    SERVICE_CATALOG,
    format_price_display,
)
from app.domain.clock import Clock, SystemClock
from app.domain.scheduling import ensure_aware_utc, get_timezone, to_utc
from app.repositories import admin_dashboard_repository as repository
from app.schemas.admin_dashboard import (
    AdminAppointmentItem,
    AppointmentServiceItem,
    AppointmentSummary,
    AppointmentsResponse,
    BusyHourItem,
    BusyDayItem,
    BusyHoursResponse,
    BarbershopSettingsResponse,
    CancellationItem,
    CancellationsResponse,
    ClientRankingItem,
    ClientsResponse,
    ClientSummary,
    DashboardPeriod,
    DashboardSummary,
    MonthComparison,
    MonthComparisonDifference,
    MonthComparisonItem,
    OccupancySummary,
    PublicBusinessHourItem,
    PublicPromotionItem,
    PublicServiceItem,
    RevenueByServiceItem,
    RevenueResponse,
    RevenueSummary,
    ServiceRankingItem,
    ServicesRanking,
)

VALID_APPOINTMENT_STATUSES = {"scheduled", "cancelled", "completed", "no_show"}
REVENUE_NOTICE = (
    "Os valores são estimativas com base nos agendamentos. "
    "O sistema ainda não valida pagamentos recebidos."
)
MONTH_LABELS = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Marco",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}
WEEKDAY_LABELS = {
    0: "Segunda",
    1: "Terça",
    2: "Quarta",
    3: "Quinta",
    4: "Sexta",
    5: "Sábado",
    6: "Domingo",
}


def mask_phone(phone: str) -> str:
    clean = "".join(character for character in phone if character.isdigit())
    if len(clean) <= 6:
        return "*" * len(clean)
    return f"{clean[:2]}******{clean[-4:]}"


def _percent_growth(current: int, previous: int) -> float | None:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_label(value: date) -> str:
    return f"{MONTH_LABELS[value.month]}/{value.year}"


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _local_month_range(month: date, timezone_name: str) -> tuple[datetime, datetime]:
    zone = get_timezone(timezone_name)
    start = datetime.combine(_month_start(month), time.min, tzinfo=zone)
    end = datetime.combine(_next_month(month), time.min, tzinfo=zone)
    return to_utc(start), to_utc(end)


def _local_period_range(period: str, now_utc: datetime, timezone_name: str) -> tuple[date, datetime, datetime]:
    now_local = ensure_aware_utc(now_utc).astimezone(get_timezone(timezone_name))
    current_month = _month_start(now_local.date())
    if period == "previous_month":
        month = _previous_month(current_month)
        start_at, end_at = _local_month_range(month, timezone_name)
        return month, start_at, end_at
    if period == "last_90_days":
        zone = get_timezone(timezone_name)
        local_start = datetime.combine(now_local.date() - timedelta(days=89), time.min, tzinfo=zone)
        local_end = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=zone)
        return local_start.date(), to_utc(local_start), to_utc(local_end)
    start_at, end_at = _local_month_range(current_month, timezone_name)
    return current_month, start_at, end_at


def _local_day_range(day: date, timezone_name: str) -> tuple[datetime, datetime]:
    zone = get_timezone(timezone_name)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return to_utc(start), to_utc(end)


def _format_time(value: datetime, timezone_name: str) -> str:
    local = ensure_aware_utc(value).astimezone(get_timezone(timezone_name))
    return local.strftime("%H:%M")


def _format_date(value: datetime, timezone_name: str) -> str:
    local = ensure_aware_utc(value).astimezone(get_timezone(timezone_name))
    return local.date().isoformat()


def _sanitize_reason(value: str | None) -> str | None:
    if value is None:
        return None
    clean = " ".join(value.split())
    return clean[:160] if clean else None


def _available_minutes_for_month(
    *,
    month: date,
    business_hours: list[repository.BusinessHoursRow],
) -> int:
    _, last_day = monthrange(month.year, month.month)
    total = 0
    for day_number in range(1, last_day + 1):
        current_day = date(month.year, month.month, day_number)
        for interval in business_hours:
            if interval.weekday == current_day.weekday():
                total += max(interval.closes_at_minutes - interval.opens_at_minutes, 0)
    return total


class AdminDashboardService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.clock = clock or SystemClock()
        self.instance = settings.barbershop_instance
        self.resource_key = settings.default_resource_key
        self.timezone_name = settings.barbershop_timezone

    async def dashboard_summary(self) -> DashboardSummary:
        now_local = ensure_aware_utc(self.clock.now_utc()).astimezone(
            get_timezone(self.timezone_name)
        )
        current_month = _month_start(now_local.date())
        previous_month = _previous_month(current_month)
        current_start, current_end = _local_month_range(current_month, self.timezone_name)
        previous_start, previous_end = _local_month_range(previous_month, self.timezone_name)

        current_count = await repository.count_appointments(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        previous_count = await repository.count_appointments(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=previous_start,
            end_at=previous_end,
        )
        status_counts = {
            item.status: item.count
            for item in await repository.count_appointments_by_status(
                self.session,
                instance=self.instance,
                resource_key=self.resource_key,
                start_at=current_start,
                end_at=current_end,
            )
        }
        current_revenue = await repository.sum_estimated_revenue(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        previous_revenue = await repository.sum_estimated_revenue(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=previous_start,
            end_at=previous_end,
        )
        estimated_slugs = {
            item.slug
            for item in SERVICE_CATALOG
            if item.requires_quote or item.price_type == "starting_at"
        }
        has_estimates = await repository.has_estimated_services(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
            estimated_service_slugs=estimated_slugs,
        )
        current_clients = await repository.count_unique_clients(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        previous_clients = await repository.count_unique_clients(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=previous_start,
            end_at=previous_end,
        )
        scheduled_minutes = await repository.sum_scheduled_minutes(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        business_hours = await repository.list_business_hours(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
        )
        available_minutes = _available_minutes_for_month(
            month=current_month,
            business_hours=business_hours,
        )
        occupancy_percent = (
            None
            if available_minutes == 0
            else round((scheduled_minutes / available_minutes) * 100, 2)
        )

        return DashboardSummary(
            period=DashboardPeriod(
                timezone=self.timezone_name,
                current_month=_month_key(current_month),
                previous_month=_month_key(previous_month),
            ),
            appointments=AppointmentSummary(
                scheduled_this_month=current_count,
                scheduled_previous_month=previous_count,
                growth_percent=_percent_growth(current_count, previous_count),
                completed_this_month=status_counts.get("completed", 0),
                cancelled_this_month=status_counts.get("cancelled", 0),
                no_show_this_month=status_counts.get("no_show", 0),
            ),
            revenue=RevenueSummary(
                estimated_this_month_cents=current_revenue,
                estimated_previous_month_cents=previous_revenue,
                growth_percent=_percent_growth(current_revenue, previous_revenue),
                has_estimates=has_estimates,
            ),
            clients=ClientSummary(
                unique_clients_this_month=current_clients,
                unique_clients_previous_month=previous_clients,
            ),
            occupancy=OccupancySummary(
                scheduled_minutes=scheduled_minutes,
                available_minutes=available_minutes,
                occupancy_percent=occupancy_percent,
            ),
        )

    async def month_comparison(self) -> MonthComparison:
        summary = await self.dashboard_summary()
        current_month = date.fromisoformat(f"{summary.period.current_month}-01")
        previous_month = date.fromisoformat(f"{summary.period.previous_month}-01")
        appointment_difference = (
            summary.appointments.scheduled_this_month
            - summary.appointments.scheduled_previous_month
        )
        revenue_difference = (
            summary.revenue.estimated_this_month_cents
            - summary.revenue.estimated_previous_month_cents
        )
        return MonthComparison(
            current_month=MonthComparisonItem(
                label=_month_label(current_month),
                appointments=summary.appointments.scheduled_this_month,
                estimated_revenue_cents=summary.revenue.estimated_this_month_cents,
            ),
            previous_month=MonthComparisonItem(
                label=_month_label(previous_month),
                appointments=summary.appointments.scheduled_previous_month,
                estimated_revenue_cents=summary.revenue.estimated_previous_month_cents,
            ),
            difference=MonthComparisonDifference(
                appointments=appointment_difference,
                appointments_percent=summary.appointments.growth_percent,
                estimated_revenue_cents=revenue_difference,
                estimated_revenue_percent=summary.revenue.growth_percent,
            ),
        )

    async def services_ranking(self, *, period: str = "current_month", limit: int = 10) -> ServicesRanking:
        _, start_at, end_at = _local_period_range(
            period,
            self.clock.now_utc(),
            self.timezone_name,
        )
        rows = await repository.list_service_ranking(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
        )
        most = sorted(rows, key=lambda item: (-item.count, -item.estimated_revenue_cents, item.service_name))
        least = sorted(rows, key=lambda item: (item.count, item.estimated_revenue_cents, item.service_name))
        safe_limit = max(1, min(limit, 50))
        return ServicesRanking(
            most_booked=[self._ranking_item(item) for item in most[:safe_limit]],
            least_booked=[self._ranking_item(item) for item in least[:safe_limit]],
        )

    async def appointments(self, *, local_date: date | None, status: str) -> AppointmentsResponse:
        if status != "all" and status not in VALID_APPOINTMENT_STATUSES:
            status = "scheduled"
        if local_date is None:
            local_date = ensure_aware_utc(self.clock.now_utc()).astimezone(
                get_timezone(self.timezone_name)
            ).date()
        start_at, end_at = _local_day_range(local_date, self.timezone_name)
        rows = await repository.list_appointments_for_day(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
            status=None if status == "all" else status,
        )
        return AppointmentsResponse(
            date=local_date.isoformat(),
            timezone=self.timezone_name,
            appointments=[
                AdminAppointmentItem(
                    id=item.id,
                    confirmation_code=item.confirmation_code,
                    status=item.status,
                    start_time=_format_time(item.start_at, self.timezone_name),
                    end_time=_format_time(item.end_at, self.timezone_name),
                    customer_name=item.customer_name,
                    phone_masked=mask_phone(item.phone) if item.phone else None,
                    services=[
                        AppointmentServiceItem(
                            name=service.name,
                            duration_minutes=service.duration_minutes,
                            price_cents=service.price_cents,
                        )
                        for service in item.services
                    ],
                    total_duration_minutes=item.total_duration_minutes,
                    total_price_cents=item.total_price_cents,
                    resource_key=item.resource_key,
                    barber_name="Daniel" if item.resource_key == "daniel" else "Lucas",
                )
                for item in rows
            ],
        )

    async def busy_hours(self) -> list[BusyHourItem]:
        _, start_at, end_at = _local_period_range(
            "current_month",
            self.clock.now_utc(),
            self.timezone_name,
        )
        rows = await repository.list_appointments_for_day(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
            status=None,
        )
        counts: dict[str, int] = {}
        for item in rows:
            if item.status == "cancelled":
                continue
            hour = ensure_aware_utc(item.start_at).astimezone(
                get_timezone(self.timezone_name)
            ).strftime("%H:00")
            counts[hour] = counts.get(hour, 0) + 1
        return [
            BusyHourItem(hour=hour, appointments=count)
            for hour, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    async def busy_hours_detail(self) -> BusyHoursResponse:
        month, start_at, end_at = _local_period_range(
            "current_month",
            self.clock.now_utc(),
            self.timezone_name,
        )
        rows = await repository.list_appointments_for_range(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
            statuses={"scheduled", "completed", "no_show"},
        )
        hour_counts: dict[str, int] = {}
        weekday_counts: dict[int, int] = {}
        for item in rows:
            local = ensure_aware_utc(item.start_at).astimezone(get_timezone(self.timezone_name))
            hour = local.strftime("%H:00")
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
            weekday_counts[local.weekday()] = weekday_counts.get(local.weekday(), 0) + 1

        scheduled_minutes = await repository.sum_scheduled_minutes(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
        )
        business_hours = await repository.list_business_hours(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
        )
        available_minutes = _available_minutes_for_month(month=month, business_hours=business_hours)
        occupancy_percent = (
            None
            if available_minutes == 0
            else round((scheduled_minutes / available_minutes) * 100, 2)
        )
        return BusyHoursResponse(
            hours=[
                BusyHourItem(hour=hour, appointments=count)
                for hour, count in sorted(hour_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            weekdays=[
                BusyDayItem(weekday=weekday, label=WEEKDAY_LABELS[weekday], appointments=count)
                for weekday, count in sorted(
                    weekday_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            occupancy=OccupancySummary(
                scheduled_minutes=scheduled_minutes,
                available_minutes=available_minutes,
                occupancy_percent=occupancy_percent,
            ),
        )

    async def revenue(self) -> RevenueResponse:
        comparison = await self.month_comparison()
        month, start_at, end_at = _local_period_range(
            "current_month",
            self.clock.now_utc(),
            self.timezone_name,
        )
        ranking = await repository.list_service_ranking(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
        )
        considered_rows = await repository.list_appointments_for_range(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=start_at,
            end_at=end_at,
            statuses={"scheduled", "completed"},
        )
        considered_appointments = len(considered_rows)
        current_revenue = comparison.current_month.estimated_revenue_cents
        ticket_average = (
            None if considered_appointments == 0 else round(current_revenue / considered_appointments)
        )
        return RevenueResponse(
            current_month=comparison.current_month,
            previous_month=comparison.previous_month,
            difference=comparison.difference,
            ticket_average_cents=ticket_average,
            considered_appointments=considered_appointments,
            by_service=[
                RevenueByServiceItem(
                    service_slug=item.service_slug,
                    service_name=item.service_name,
                    appointments=item.count,
                    estimated_revenue_cents=item.estimated_revenue_cents,
                )
                for item in sorted(ranking, key=lambda item: (-item.estimated_revenue_cents, item.service_name))
            ],
            notice=REVENUE_NOTICE,
        )

    async def clients(self, *, limit: int = 10) -> ClientsResponse:
        now_utc = ensure_aware_utc(self.clock.now_utc())
        _, current_start, current_end = _local_period_range("current_month", now_utc, self.timezone_name)
        previous_month = _previous_month(
            _month_start(now_utc.astimezone(get_timezone(self.timezone_name)).date())
        )
        previous_start, previous_end = _local_month_range(previous_month, self.timezone_name)
        current_unique = await repository.count_unique_clients(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        previous_unique = await repository.count_unique_clients(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=previous_start,
            end_at=previous_end,
        )
        rows = await repository.list_client_activity(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
            now_at=now_utc,
            limit=max(1, min(limit, 50)),
        )
        return ClientsResponse(
            unique_clients_this_month=current_unique,
            unique_clients_previous_month=previous_unique,
            recurring_clients=sum(1 for item in rows if item.appointments > 1),
            top_clients=[
                ClientRankingItem(
                    customer_name=item.customer_name,
                    phone_masked=mask_phone(item.phone) if item.phone else None,
                    appointments=item.appointments,
                    last_appointment=(
                        _format_date(item.last_appointment_at, self.timezone_name)
                        if item.last_appointment_at
                        else None
                    ),
                    next_appointment=(
                        _format_date(item.next_appointment_at, self.timezone_name)
                        if item.next_appointment_at
                        else None
                    ),
                )
                for item in rows
            ],
        )

    async def cancellations(self) -> CancellationsResponse:
        now_utc = ensure_aware_utc(self.clock.now_utc())
        _, current_start, current_end = _local_period_range("current_month", now_utc, self.timezone_name)
        previous_month = _previous_month(
            _month_start(now_utc.astimezone(get_timezone(self.timezone_name)).date())
        )
        previous_start, previous_end = _local_month_range(previous_month, self.timezone_name)
        current_status = {
            item.status: item.count
            for item in await repository.count_appointments_by_status(
                self.session,
                instance=self.instance,
                resource_key=self.resource_key,
                start_at=current_start,
                end_at=current_end,
            )
        }
        previous_status = {
            item.status: item.count
            for item in await repository.count_appointments_by_status(
                self.session,
                instance=self.instance,
                resource_key=self.resource_key,
                start_at=previous_start,
                end_at=previous_end,
            )
        }
        total = await repository.count_appointments(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
        )
        cancelled = current_status.get("cancelled", 0)
        rate = None if total == 0 else round((cancelled / total) * 100, 2)
        rows = await repository.list_appointments_for_range(
            self.session,
            instance=self.instance,
            resource_key=self.resource_key,
            start_at=current_start,
            end_at=current_end,
            statuses={"cancelled", "no_show"},
        )
        rows = sorted(rows, key=lambda item: item.start_at, reverse=True)[:20]
        return CancellationsResponse(
            cancelled_this_month=cancelled,
            cancelled_previous_month=previous_status.get("cancelled", 0),
            no_show_this_month=current_status.get("no_show", 0),
            cancellation_rate_percent=rate,
            recent=[
                CancellationItem(
                    date=_format_date(item.start_at, self.timezone_name),
                    time=_format_time(item.start_at, self.timezone_name),
                    customer_name=item.customer_name,
                    phone_masked=mask_phone(item.phone) if item.phone else None,
                    services=[service.name for service in item.services],
                    status=item.status,
                    reason=_sanitize_reason(item.cancellation_reason),
                    resource_key=item.resource_key,
                    barber_name="Daniel" if item.resource_key == "daniel" else "Lucas",
                )
                for item in rows
            ],
        )

    def barbershop_settings(self) -> BarbershopSettingsResponse:
        public_name = "O Original Barbershop"
        return BarbershopSettingsResponse(
            public_name=public_name,
            address=FULL_ADDRESS,
            google_maps_url=GOOGLE_MAPS_URL,
            business_hours=[
                PublicBusinessHourItem(
                    weekday=item.weekday,
                    label=WEEKDAY_LABELS[item.weekday],
                    opens_at=item.opens_at,
                    closes_at=item.closes_at,
                )
                for item in BUSINESS_HOURS_CATALOG
            ],
            payment_methods=[item["display_name"] for item in PAYMENT_METHODS],
            delay_tolerance="Não configurada no dashboard.",
            cancellation_policy="Cancelamentos seguem o fluxo de atendimento atual.",
            services=[
                PublicServiceItem(
                    slug=item.slug,
                    name=item.name,
                    duration_minutes=item.duration_minutes,
                    price_cents=item.price_cents,
                    price_type=item.price_type,
                    requires_quote=item.requires_quote,
                    active=item.booking_enabled,
                )
                for item in SERVICE_CATALOG
            ],
            featured_services=["Corte Degradê", "Barba - Alinhamento", "Platinado / Luzes"],
            upsell="Combo Corte + Barba + Sobrancelha como oferta informativa.",
            promotion=PublicPromotionItem(
                name=str(PROMOTION["name"]),
                price_cents=int(PROMOTION["price_cents"]),
                estimated_duration_minutes=int(PROMOTION["estimated_duration_minutes"]),
                booking_enabled=bool(PROMOTION["booking_enabled"]),
                pending_note=str(PROMOTION["pending_note"]),
            ),
            pending_items=[
                "Modalidades de corte do combo ainda não confirmadas.",
            ],
        )

    def _ranking_item(self, item: repository.ServiceRankingRow) -> ServiceRankingItem:
        return ServiceRankingItem(
            service_slug=item.service_slug,
            service_name=item.service_name,
            count=item.count,
            estimated_revenue_cents=item.estimated_revenue_cents,
            average_duration_minutes=item.average_duration_minutes,
        )
