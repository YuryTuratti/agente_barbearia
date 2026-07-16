from pydantic import BaseModel, ConfigDict


class DashboardPeriod(BaseModel):
    model_config = ConfigDict(frozen=True)

    timezone: str
    current_month: str
    previous_month: str


class AppointmentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    scheduled_this_month: int
    scheduled_previous_month: int
    growth_percent: float | None
    completed_this_month: int
    cancelled_this_month: int
    no_show_this_month: int


class RevenueSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    estimated_this_month_cents: int
    estimated_previous_month_cents: int
    growth_percent: float | None
    has_estimates: bool


class ClientSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    unique_clients_this_month: int
    unique_clients_previous_month: int


class OccupancySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    scheduled_minutes: int
    available_minutes: int
    occupancy_percent: float | None


class DashboardSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: DashboardPeriod
    appointments: AppointmentSummary
    revenue: RevenueSummary
    clients: ClientSummary
    occupancy: OccupancySummary


class ServiceRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_slug: str
    service_name: str
    count: int
    estimated_revenue_cents: int
    average_duration_minutes: float | None = None


class ServicesRanking(BaseModel):
    model_config = ConfigDict(frozen=True)

    most_booked: list[ServiceRankingItem]
    least_booked: list[ServiceRankingItem]


class AppointmentServiceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    duration_minutes: int
    price_cents: int


class AdminAppointmentItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    confirmation_code: str
    status: str
    start_time: str
    end_time: str
    customer_name: str | None
    phone_masked: str | None
    services: list[AppointmentServiceItem]
    total_duration_minutes: int
    total_price_cents: int
    resource_key: str = "main"
    barber_name: str = "Lucas"


class AppointmentsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    timezone: str
    appointments: list[AdminAppointmentItem]


class BusyHourItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    hour: str
    appointments: int


class BusyDayItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    weekday: int
    label: str
    appointments: int


class BusyHoursResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    hours: list[BusyHourItem]
    weekdays: list[BusyDayItem]
    occupancy: OccupancySummary


class MonthComparisonItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    appointments: int
    estimated_revenue_cents: int


class MonthComparisonDifference(BaseModel):
    model_config = ConfigDict(frozen=True)

    appointments: int
    appointments_percent: float | None
    estimated_revenue_cents: int
    estimated_revenue_percent: float | None


class MonthComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_month: MonthComparisonItem
    previous_month: MonthComparisonItem
    difference: MonthComparisonDifference


class RevenueByServiceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_slug: str
    service_name: str
    appointments: int
    estimated_revenue_cents: int


class RevenueResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_month: MonthComparisonItem
    previous_month: MonthComparisonItem
    difference: MonthComparisonDifference
    ticket_average_cents: int | None
    considered_appointments: int
    by_service: list[RevenueByServiceItem]
    notice: str


class ClientRankingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_name: str | None
    phone_masked: str | None
    appointments: int
    last_appointment: str | None
    next_appointment: str | None


class ClientsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    unique_clients_this_month: int
    unique_clients_previous_month: int
    recurring_clients: int
    top_clients: list[ClientRankingItem]


class CancellationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    time: str
    customer_name: str | None
    phone_masked: str | None
    services: list[str]
    status: str
    reason: str | None
    resource_key: str = "main"
    barber_name: str = "Lucas"


class CancellationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    cancelled_this_month: int
    cancelled_previous_month: int
    no_show_this_month: int
    cancellation_rate_percent: float | None
    recent: list[CancellationItem]


class PublicBusinessHourItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    weekday: int
    label: str
    opens_at: str
    closes_at: str


class PublicServiceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    duration_minutes: int
    price_cents: int
    price_type: str
    requires_quote: bool
    active: bool


class PublicPromotionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    price_cents: int
    estimated_duration_minutes: int
    booking_enabled: bool
    pending_note: str | None


class BarbershopSettingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    public_name: str
    address: str | None
    google_maps_url: str | None
    business_hours: list[PublicBusinessHourItem]
    payment_methods: list[str]
    delay_tolerance: str
    cancellation_policy: str
    services: list[PublicServiceItem]
    featured_services: list[str]
    upsell: str | None
    promotion: PublicPromotionItem | None
    pending_items: list[str]
