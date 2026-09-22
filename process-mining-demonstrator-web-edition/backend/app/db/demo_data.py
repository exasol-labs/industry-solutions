"""Demo-data generators — synthetic process-mining event logs that can be loaded
into a target schema so a fresh connection has something to explore.

The datasets (registered in ``DATASETS``):

* ``retail``  — "Online Bookstore" order lifecycle (a faithful port of the macOS
  app's BookstoreGen). Login → browse → basket → checkout → payment → fulfilment →
  delivery, with a returns flow and a deliberately unreliable bank-transfer path.
* ``finance`` — "Online Credit Application". Bank/Affiliate intake → application
  check (with a rework loop) → credit assessment → score/sum-driven approval (with
  agent review loops) → acceptance and payment, or rejection.
* ``transportation`` — "Flight Booking & Management". Star-Alliance-style search /
  select / book / pay, with interline itineraries and a manage-booking branch.
* ``airport`` — "Airport Passenger Flow" (a port of the ``paxflow`` generator).
  A departing passenger's terminal walk; a *streamed* dataset, so it scales to
  1,000,000+ journeys without materialising every event in memory.

Both reuse the canonical tables from schema_ddl (so NOTES et al. exist too) and only
ever touch their own project's rows. Loading requires a database account with
CREATE SCHEMA / CREATE TABLE / INSERT rights, which only a database administrator
can grant — the application cannot.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_JOURNEYS = 20_000  # in-memory datasets: bound insert time / request duration
# Streamed datasets (a per-journey generator, so memory stays flat) allow far more —
# the Airport Passenger Flow demo defaults to 1,000,000. This ceiling only guards
# against a pathological request; raise it if a larger single load is ever needed.
MAX_JOURNEYS_STREAMED = 10_000_000
_BATCH_SIZE = 200
_STREAM_BATCH_ROWS = 2_000  # rows per INSERT on the streamed path

# name, description, bg, fg, score, shape, end_of_process, belongs_to
StepDef = tuple[str, str, str, str, int, str, int, str]


@dataclass
class JEvent:
    event_id: str
    step: str
    step_id: int
    event_time: datetime
    meta1: str
    meta2: str
    meta3: str


@dataclass
class DemoDataset:
    key: str
    title_short: str
    title: str
    description: str
    meta_titles: tuple[str, str, str]
    step_defs: list[StepDef]
    generate: Callable[[int, random.Random], list[JEvent]]
    # Optional per-journey generator. When present, the loader streams journeys in
    # batches (flat memory) instead of materialising them all, which is what lets a
    # dataset go to millions of journeys. `generate` stays the batch entry point
    # (used by tests and the in-memory path).
    generate_one: Callable[[int, random.Random], list[JEvent]] | None = None


# ── shared helpers ────────────────────────────────────────────────────────────


def _weighted_choice(dist: list[tuple[str, float]], rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for item, w in dist:
        cum += w
        if r < cum:
            return item
    return dist[-1][0]


def _md5_id(raw: str) -> str:
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _rand_start(rng: random.Random) -> datetime:
    start = datetime(2024, 1, 1, 8)
    end = datetime(2024, 12, 31, 22)
    span = (end - start).total_seconds()
    return start + timedelta(seconds=rng.uniform(0, span))


# ── retail: Online Bookstore ──────────────────────────────────────────────────

_RETAIL_RETURN_RATE = 0.05
_RETAIL_PAYMENTS = [("Credit Card", 0.45), ("PayPal", 0.35), ("Bank Transfer", 0.20)]
_RETAIL_SEGMENTS = [("New", 0.30), ("Regular", 0.50), ("Premium", 0.20)]
_RETAIL_ORDER_VALS = [
    ("Low (<30 EUR)", 0.40),
    ("Medium (30-100 EUR)", 0.40),
    ("High (>100 EUR)", 0.20),
]

_RETAIL_STEP_DEFS: list[StepDef] = [
    ("Login", "Customer authenticates", "3498DB", "FFFFFF", 0, "round", 0, "Customer Interaction"),
    ("Browse Catalog", "Customer browses book listings", "5DADE2", "FFFFFF", 0, "round", 0, "Customer Interaction"),
    ("View Book Details", "Customer views a single book page", "85C1E9", "FFFFFF", 0, "round", 0, "Customer Interaction"),
    ("Add to Basket", "Customer adds a book to shopping basket", "27AE60", "FFFFFF", 5, "round", 0, "Customer Interaction"),
    ("View Basket", "Customer reviews basket before checkout", "2ECC71", "FFFFFF", 0, "round", 0, "Customer Interaction"),
    ("Checkout", "Customer initiates checkout flow", "E67E22", "FFFFFF", 0, "round", 0, "Purchase Process"),
    ("Enter Shipping Address", "Customer enters or confirms delivery address", "CA6F1E", "FFFFFF", 0, "round", 0, "Purchase Process"),
    ("Select Payment Method", "Customer chooses a payment method", "D35400", "FFFFFF", 0, "round", 0, "Purchase Process"),
    ("Payment: Credit Card", "Credit card payment selected", "F0B27A", "000000", 0, "round", 0, "Payment"),
    ("Payment: PayPal", "PayPal payment selected", "F7DC6F", "000000", 0, "round", 0, "Payment"),
    ("Payment: Bank Transfer", "Bank transfer — known reliability issues", "C0392B", "FFFFFF", -5, "round", 0, "Payment"),
    ("Payment Processing", "Payment gateway processing the transaction", "BDC3C7", "000000", 0, "round", 0, "Payment"),
    ("Payment Failed", "Transaction declined or timed out", "E74C3C", "FFFFFF", -10, "hex", 0, "Payment"),
    ("Payment Retry", "Customer retries a failed payment", "E59866", "000000", -5, "round", 0, "Payment"),
    ("Payment Confirmed", "Payment successfully authorised", "1ABC9C", "FFFFFF", 10, "stadium", 0, "Payment"),
    ("Order Confirmed", "Order reference issued to customer", "16A085", "FFFFFF", 10, "stadium", 0, "Purchase Process"),
    ("Warehouse Picking", "Books located and picked from shelves", "8E44AD", "FFFFFF", 0, "round", 0, "Fulfilment"),
    ("Warehouse Packing", "Order packed and label printed", "7D3C98", "FFFFFF", 0, "round", 0, "Fulfilment"),
    ("Shipped", "Package handed over to carrier", "2980B9", "FFFFFF", 5, "round", 0, "Fulfilment"),
    ("Delivered", "Package confirmed as delivered", "229954", "FFFFFF", 15, "stadium", 1, "Fulfilment"),
    ("Return Initiated", "Customer requests return authorisation", "C0392B", "FFFFFF", -10, "hex", 0, "Returns"),
    ("Return Shipped", "Customer sends package back", "E74C3C", "FFFFFF", 0, "round", 0, "Returns"),
    ("Return Received", "Returned package received at warehouse", "D98880", "FFFFFF", 0, "round", 0, "Returns"),
    ("Refund Processed", "Refund issued to original payment method", "F1948A", "000000", -5, "stadium", 1, "Returns"),
]


def _generate_retail_journey(
    event_id: str, t0: datetime, payment: str, segment: str, order_val: str, rng: random.Random
) -> list[JEvent]:
    rows: list[JEvent] = []
    ids = step_id_map(_RETAIL_STEP_DEFS)
    state = {"t": t0}

    def add(step: str, lo: int, hi: int) -> None:
        # STEP_ID is now the stable activity id; advance the clock by ≥1s so events
        # within a journey have strictly increasing timestamps (unambiguous order).
        state["t"] = state["t"] + timedelta(seconds=max(1, rng.randint(lo, hi)))
        rows.append(JEvent(event_id, step, ids[step], state["t"], payment, segment, order_val))

    add("Login", 5, 60)
    for _ in range(rng.randint(1, 4)):
        add("Browse Catalog", 20, 300)
        if rng.random() < 0.65:
            add("View Book Details", 20, 180)
            if rng.random() < 0.18:
                add("Browse Catalog", 10, 90)
    for _ in range(rng.randint(1, 3)):
        add("Add to Basket", 5, 25)
    if rng.random() < 0.72:
        add("View Basket", 10, 90)

    add("Checkout", 10, 45)
    add("Enter Shipping Address", 45, 240)
    add("Select Payment Method", 10, 35)

    success = False
    if payment == "Bank Transfer":
        add("Payment: Bank Transfer", 30, 120)
        for attempt in range(3):
            add("Payment Processing", 180, 900)
            if rng.random() < 0.35:
                add("Payment Failed", 5, 15)
                if attempt < 2 and rng.random() < 0.55:
                    add("Payment Retry", 90, 480)
                    continue
                return rows
            success = True
            break
    elif payment == "PayPal":
        add("Payment: PayPal", 10, 35)
        add("Payment Processing", 8, 25)
        if rng.random() < 0.03:
            add("Payment Failed", 5, 10)
            return rows
        success = True
    else:
        add("Payment: Credit Card", 20, 90)
        add("Payment Processing", 5, 20)
        if rng.random() < 0.02:
            add("Payment Failed", 5, 10)
            return rows
        success = True

    if not success:
        return rows

    add("Payment Confirmed", 5, 10)
    add("Order Confirmed", 5, 10)
    add("Warehouse Picking", 3_600, 28_800)
    add("Warehouse Packing", 1_800, 7_200)
    add("Shipped", 3_600, 86_400)
    add("Delivered", 86_400, 604_800)

    if rng.random() < _RETAIL_RETURN_RATE:
        add("Return Initiated", 3_600, 604_800)
        add("Return Shipped", 86_400, 259_200)
        add("Return Received", 86_400, 604_800)
        add("Refund Processed", 3_600, 86_400)

    return rows


def generate_retail_rows(count: int, rng: random.Random | None = None) -> list[JEvent]:
    rng = rng or random.Random()
    rows: list[JEvent] = []
    for i in range(count):
        eid = _md5_id("ORD-%06d" % (i + 1))
        rows.extend(
            _generate_retail_journey(
                eid,
                _rand_start(rng),
                _weighted_choice(_RETAIL_PAYMENTS, rng),
                _weighted_choice(_RETAIL_SEGMENTS, rng),
                _weighted_choice(_RETAIL_ORDER_VALS, rng),
                rng,
            )
        )
    return rows


# ── finance: Online Credit Application ────────────────────────────────────────

_FIN_CHANNELS = [("Bank", 0.55), ("Affiliate", 0.45)]
_FIN_INCOME = [("Low", 0.30), ("Medium", 0.45), ("High", 0.25)]
# label, lo, hi, weight — the numeric sum drives the >10.000 EUR rule and payment delay.
_FIN_SUM_BANDS = [
    ("< 5.000 EUR", 1_000, 5_000, 0.35),
    ("5.000–10.000 EUR", 5_000, 10_000, 0.30),
    ("10.000–25.000 EUR", 10_000, 25_000, 0.25),
    ("> 25.000 EUR", 25_000, 60_000, 0.10),
]
# credit-score band: low (<75% → auto reject), mid (75–90% → agent review), high (>90% → auto accept)
_FIN_SCORE_BANDS = [("low", 0.20), ("mid", 0.35), ("high", 0.45)]

_FINANCE_STEP_DEFS: list[StepDef] = [
    ("Bank", "Application submitted through a bank branch", "2C3E50", "FFFFFF", 0, "round", 0, "Intake"),
    ("Affiliate", "Application submitted through an affiliate / online shop", "34495E", "FFFFFF", 0, "round", 0, "Intake"),
    ("Application Received", "Application registered in the system", "5D6D7E", "FFFFFF", 0, "round", 0, "Intake"),
    ("Application Checked", "Application completeness verified", "5DADE2", "FFFFFF", 0, "round", 0, "Intake"),
    ("Additional Information Requested", "Applicant asked to supply missing information", "E59866", "000000", -5, "hex", 0, "Intake"),
    ("Credit Assessment", "Automated credit assessment (bank channel)", "8E44AD", "FFFFFF", 0, "round", 0, "Assessment"),
    ("Credit Check", "Automated credit check (affiliate channel)", "9B59B6", "FFFFFF", 0, "round", 0, "Assessment"),
    ("Agent Review", "Manual review by a credit agent", "F39C12", "000000", -5, "round", 0, "Assessment"),
    ("Senior Agent Approval", "Additional approval required for high credit sums", "D68910", "000000", 0, "round", 0, "Assessment"),
    ("Accepted", "Credit application accepted", "1ABC9C", "FFFFFF", 10, "stadium", 0, "Decision"),
    ("Rejected", "Credit application rejected", "E74C3C", "FFFFFF", -15, "hex", 1, "Decision"),
    ("Payment to Applicant", "Disbursement initiated to the applicant", "16A085", "FFFFFF", 5, "round", 0, "Disbursement"),
    ("Payment", "Funds paid out to the applicant", "229954", "FFFFFF", 15, "stadium", 1, "Disbursement"),
]


def _pick_sum(rng: random.Random) -> tuple[str, int]:
    r = rng.random()
    cum = 0.0
    for label, lo, hi, w in _FIN_SUM_BANDS:
        cum += w
        if r < cum:
            return label, rng.randint(lo, hi)
    label, lo, hi, _w = _FIN_SUM_BANDS[-1]
    return label, rng.randint(lo, hi)


def _generate_finance_journey(
    event_id: str,
    t0: datetime,
    channel: str,
    income: str,
    sum_label: str,
    sum_amount: int,
    score_band: str,
    rng: random.Random,
) -> list[JEvent]:
    rows: list[JEvent] = []
    ids = step_id_map(_FINANCE_STEP_DEFS)
    state = {"t": t0}

    def add(step: str, lo: int, hi: int) -> None:
        state["t"] = state["t"] + timedelta(seconds=max(1, rng.randint(lo, hi)))
        # meta1 = applied credit sum, meta2 = income class, meta3 = channel (Bank/Affiliate).
        # STEP_ID is the stable activity id; ≥1s advance keeps order unambiguous.
        rows.append(JEvent(event_id, step, ids[step], state["t"], sum_label, income, channel))

    add(channel, 0, 60)  # entry point — "Bank" or "Affiliate"
    add("Application Received", 30, 300)
    add("Application Checked", 300, 3_600)
    # 20% of applications require additional information — rework loop.
    loops = 0
    while rng.random() < 0.20 and loops < 2:
        add("Additional Information Requested", 3_600, 172_800)
        add("Application Checked", 1_800, 7_200)
        loops += 1

    assessment = "Credit Assessment" if channel == "Bank" else "Credit Check"
    add(assessment, 60, 1_800)

    # Credit score: <75% auto-reject, 75–90% agent review (50% reject), >90% auto-accept.
    if score_band == "low":
        add("Rejected", 30, 300)
        return rows
    if score_band == "mid":
        add("Agent Review", 3_600, 172_800)
        if rng.random() < 0.50:
            add("Rejected", 60, 600)
            return rows

    # Positive assessment. Large sums need an additional agent, 5% of which decline.
    if sum_amount > 10_000:
        add("Senior Agent Approval", 3_600, 259_200)
        if rng.random() < 0.05:
            add("Rejected", 60, 600)
            return rows

    add("Accepted", 60, 1_800)
    add("Payment to Applicant", 300, 7_200)
    # Payout takes up to ~7 days; higher sums take longer, affiliate channel is faster.
    frac = min(sum_amount / 30_000.0, 1.0)
    base_days = 1.0 + 6.0 * frac
    if channel == "Affiliate":
        base_days *= 0.5
    delay = max(3_600, int(base_days * 86_400 * rng.uniform(0.7, 1.15)))
    add("Payment", delay, delay)
    return rows


def generate_finance_rows(count: int, rng: random.Random | None = None) -> list[JEvent]:
    rng = rng or random.Random()
    rows: list[JEvent] = []
    for i in range(count):
        eid = _md5_id("CRA-%06d" % (i + 1))
        sum_label, sum_amount = _pick_sum(rng)
        rows.extend(
            _generate_finance_journey(
                eid,
                _rand_start(rng),
                _weighted_choice(_FIN_CHANNELS, rng),
                _weighted_choice(_FIN_INCOME, rng),
                sum_label,
                sum_amount,
                _weighted_choice(_FIN_SCORE_BANDS, rng),
                rng,
            )
        )
    return rows


# ── transportation: Flight Booking & Management ───────────────────────────────
#
# Star Alliance-flavoured airlines and hubs. 80% of journeys are a new booking
# (search → select → book → pay → confirm); 20% only manage an existing booking
# (seat reservation / ancillary services). 50% of new bookings are interline
# (multi-airline) itineraries, which query a partner airline's availability during
# search and connect to the partner's booking system when booking.

_TRANS_JOURNEY = [("New Booking", 0.80), ("Manage Booking", 0.20)]
# Marketing carrier — Star Alliance members (hubs: FRA/MUC, ORD, YYZ, SIN, IST, ZRH, HND, VIE, BKK, CPH).
_TRANS_AIRLINES = [
    ("Lufthansa", 0.20),
    ("United", 0.15),
    ("Air Canada", 0.10),
    ("Singapore Airlines", 0.10),
    ("Turkish Airlines", 0.10),
    ("Swiss", 0.08),
    ("ANA", 0.08),
    ("Austrian", 0.07),
    ("Thai Airways", 0.06),
    ("SAS", 0.06),
]
_TRANS_PAYMENTS = [
    ("Credit Card", 0.45),
    ("SEPA", 0.25),
    ("Apple Pay", 0.13),
    ("Google Pay", 0.12),
    ("Advance Payment", 0.05),
]
_TRANS_INTERLINE = 0.50  # share of new bookings that span more than one airline
_TRANS_MODIFY = 0.30  # per-round chance the traveller changes the search
_TRANS_MANAGE_PAYS = 0.60  # share of manage-booking journeys that pay for extras

_TRANSPORT_STEP_DEFS: list[StepDef] = [
    ("Login", "Traveller signs in to the reservation system", "2C3E50", "FFFFFF", 0, "round", 0, "Access"),
    ("Search Flights", "Traveller submits a flight search request", "2980B9", "FFFFFF", 0, "round", 0, "Search"),
    ("Show Flight Results", "System returns a list of available flights", "5DADE2", "FFFFFF", 0, "round", 0, "Search"),
    ("Modify Search", "Traveller changes the criteria and searches again", "E67E22", "000000", -5, "hex", 0, "Search"),
    ("Query Partner Airline System", "Interline itinerary — availability requested from a partner airline", "16A085", "FFFFFF", 0, "round", 0, "Search"),
    ("Select Flight", "Traveller selects a flight from the results", "27AE60", "FFFFFF", 5, "round", 0, "Booking"),
    ("Connect Partner Booking System", "Interline booking — connects to the partner airline's booking system", "1ABC9C", "FFFFFF", 0, "round", 0, "Booking"),
    ("Create Booking", "Booking record (PNR) created", "229954", "FFFFFF", 5, "round", 0, "Booking"),
    ("Select Payment Method", "Traveller chooses a payment option", "8E44AD", "FFFFFF", 0, "round", 0, "Payment"),
    ("Process Payment", "Payment authorised and captured", "9B59B6", "FFFFFF", 5, "round", 0, "Payment"),
    ("Confirm Booking", "Booking confirmed and ticket issued", "1E8449", "FFFFFF", 15, "stadium", 1, "Payment"),
    ("Retrieve Booking", "Traveller opens an existing booking to manage it", "34495E", "FFFFFF", 0, "round", 0, "Manage"),
    ("Seat Reservation", "Traveller reserves seats", "48C9B0", "000000", 3, "round", 0, "Manage"),
    ("Add Services", "Traveller adds ancillary services (bags, meals, lounge)", "5499C7", "FFFFFF", 3, "round", 0, "Manage"),
    ("Confirm Changes", "Booking changes confirmed", "148F77", "FFFFFF", 10, "stadium", 1, "Manage"),
]


def _generate_flight_journey(
    event_id: str,
    t0: datetime,
    journey_type: str,
    airline: str,
    payment: str,
    interline: bool,
    rng: random.Random,
) -> list[JEvent]:
    rows: list[JEvent] = []
    ids = step_id_map(_TRANSPORT_STEP_DEFS)
    state = {"t": t0}

    def add(step: str, lo: int, hi: int) -> None:
        state["t"] = state["t"] + timedelta(seconds=max(1, rng.randint(lo, hi)))
        # meta1 = journey type, meta2 = airline, meta3 = payment method.
        # STEP_ID is the stable activity id; ≥1s advance keeps order unambiguous.
        rows.append(JEvent(event_id, step, ids[step], state["t"], journey_type, airline, payment))

    add("Login", 0, 120)

    if journey_type == "Manage Booking":
        add("Retrieve Booking", 20, 600)
        # At least one ancillary action, sometimes both, in either order.
        actions = ["Seat Reservation", "Add Services"]
        rng.shuffle(actions)
        if rng.random() < 0.5:
            actions = actions[:1]
        for action in actions:
            add(action, 30, 900)
        if payment != "No Payment":
            add("Select Payment Method", 10, 120)
            add("Process Payment", 5, 90)
        add("Confirm Changes", 10, 120)
        return rows

    # New booking.
    add("Search Flights", 20, 600)
    add("Show Flight Results", 2, 30)
    loops = 0
    while rng.random() < _TRANS_MODIFY and loops < 2:
        add("Modify Search", 15, 300)
        add("Show Flight Results", 2, 30)
        loops += 1
    if interline:  # multi-airline itinerary — check the partner's inventory
        add("Query Partner Airline System", 3, 40)
    add("Select Flight", 10, 300)
    if interline:  # book the partner-operated leg through their system
        add("Connect Partner Booking System", 3, 40)
    add("Create Booking", 15, 300)
    add("Select Payment Method", 10, 180)
    add("Process Payment", 5, 120)
    add("Confirm Booking", 5, 60)
    return rows


def generate_transportation_rows(
    count: int, rng: random.Random | None = None
) -> list[JEvent]:
    rng = rng or random.Random()
    rows: list[JEvent] = []
    for i in range(count):
        eid = _md5_id("FLT-%06d" % (i + 1))
        journey_type = _weighted_choice(_TRANS_JOURNEY, rng)
        airline = _weighted_choice(_TRANS_AIRLINES, rng)
        if journey_type == "New Booking":
            payment = _weighted_choice(_TRANS_PAYMENTS, rng)
            interline = rng.random() < _TRANS_INTERLINE
        else:
            payment = (
                _weighted_choice(_TRANS_PAYMENTS, rng)
                if rng.random() < _TRANS_MANAGE_PAYS
                else "No Payment"
            )
            interline = False
        rows.extend(
            _generate_flight_journey(
                eid, _rand_start(rng), journey_type, airline, payment, interline, rng
            )
        )
    return rows


# ── transportation: Airport Passenger Flow ────────────────────────────────────
#
# A faithful port of the `paxflow` generator (Building-Demo-Data/swift): a departing
# passenger's walk through the terminal, as a probabilistic state machine. From the
# Departure Hall 2% leave immediately; otherwise 28% drop a bag, 30% check in at a
# desk, 40% go straight to Security. After Security they wander the airside amenities
# (Duty Free / Lounge / Dining) in any order before boarding. Clearing Passport
# Control flips every following airside/boarding step from its domestic ("Dom") to
# its international ("Int") variant; 5% of boardings are denied.
#
# META_1 = Terminal-{1,2,3} (weights .4/.4/.2); META_2/META_3 are unused ("-").
# Dwell ranges are in MINUTES and match the Swift generator exactly.

_APF_TERMINALS = [("Terminal-1", 0.40), ("Terminal-2", 0.40), ("Terminal-3", 0.20)]

_APF_PRE_STEP_DEFS: list[StepDef] = [
    ("ENTER Departure Hall", "Passenger enters the departure hall", "2C3E50", "FFFFFF", 0, "round", 0, "Departure Hall"),
    ("LEAVE Departure Hall", "Passenger leaves without travelling", "7F8C8D", "FFFFFF", -5, "hex", 1, "Departure Hall"),
    ("ENTER Baggage Drop", "Passenger drops checked baggage", "2980B9", "FFFFFF", 0, "round", 0, "Check-in"),
    ("LEAVE Baggage Drop", "Checked baggage accepted", "5DADE2", "000000", 0, "round", 0, "Check-in"),
    ("ENTER Check-In", "Passenger checks in at the desk", "2471A3", "FFFFFF", 0, "round", 0, "Check-in"),
    ("LEAVE Check-In", "Check-in complete", "5499C7", "FFFFFF", 0, "round", 0, "Check-in"),
    ("ENTER Security Check", "Passenger enters security screening", "E67E22", "000000", 0, "round", 0, "Security"),
    ("LEAVE Security Check", "Passenger cleared security", "F39C12", "000000", 0, "round", 0, "Security"),
    ("ENTER Passport Control", "Passenger enters passport control", "8E44AD", "FFFFFF", 0, "round", 0, "Border"),
    ("LEAVE Passport Control", "Passenger cleared passport control", "9B59B6", "FFFFFF", 0, "round", 0, "Border"),
]


def _apf_airside_step_defs(sfx: str) -> list[StepDef]:
    """The airside amenity + boarding steps for one side — ``sfx`` is 'Dom' or 'Int'.
    Grouped by BELONGS_TO so the aggregate designer can collapse each airside into a
    single Σ super-step (Σ Airside Dom / Σ Airside Int)."""
    airside = "Airside Domestic" if sfx == "Dom" else "Airside International"
    return [
        (f"ENTER Duty Free {sfx}", "Passenger enters the duty-free area", "16A085", "FFFFFF", 3, "round", 0, airside),
        (f"LEAVE Duty Free {sfx}", "Passenger leaves the duty-free area", "1ABC9C", "FFFFFF", 0, "round", 0, airside),
        (f"ENTER Lounge {sfx}", "Passenger enters the lounge", "2E86C1", "FFFFFF", 3, "round", 0, airside),
        (f"LEAVE Lounge {sfx}", "Passenger leaves the lounge", "5DADE2", "000000", 0, "round", 0, airside),
        (f"ENTER Dining Area {sfx}", "Passenger enters the dining area", "CA6F1E", "FFFFFF", 2, "round", 0, airside),
        (f"LEAVE Dining Area {sfx}", "Passenger leaves the dining area", "E59866", "000000", 0, "round", 0, airside),
        (f"ENTER Boarding Gate {sfx}", "Passenger arrives at the boarding gate", "27AE60", "FFFFFF", 5, "round", 0, "Boarding"),
        (f"BOARD Aircraft {sfx}", "Passenger boards the aircraft", "1E8449", "FFFFFF", 15, "stadium", 1, "Boarding"),
        (f"DENIED Boarding {sfx}", "Passenger is denied boarding", "C0392B", "FFFFFF", -10, "hex", 1, "Boarding"),
    ]


# Pre-airside steps first, then the Dom side, then the Int side. Order fixes each
# step's STEP_ID (its 1-based position), so never reorder without a reason.
_AIRPORT_STEP_DEFS: list[StepDef] = (
    _APF_PRE_STEP_DEFS + _apf_airside_step_defs("Dom") + _apf_airside_step_defs("Int")
)
# Lazily cached: step_id_map is defined further down, so this can't run at import.
_APF_IDS: dict[str, int] = {}


def _apf_ids() -> dict[str, int]:
    if not _APF_IDS:
        _APF_IDS.update(step_id_map(_AIRPORT_STEP_DEFS))
    return _APF_IDS


def _generate_airport_journey(event_id: str, rng: random.Random) -> list[JEvent]:
    ids = _apf_ids()
    terminal = _weighted_choice(_APF_TERMINALS, rng)
    rows: list[JEvent] = []
    t = _rand_start(rng)
    # META_2/META_3 are unused in this dataset — always '-' (matches the source).
    rows.append(JEvent(event_id, "ENTER Departure Hall", ids["ENTER Departure Hall"], t, terminal, "-", "-"))

    def add(step: str, lo: int, hi: int) -> None:
        nonlocal t
        # Advance by whole minutes; ≥1 keeps EVENT_TIME strictly increasing so the
        # step order is unambiguous.
        t = t + timedelta(minutes=max(1, rng.randint(lo, hi)))
        rows.append(JEvent(event_id, step, ids[step], t, terminal, "-", "-"))

    r0 = rng.randint(1, 100)
    if r0 <= 2:  # leaves the hall without travelling → END
        add("LEAVE Departure Hall", 2, 10)
        return rows
    if r0 <= 30:  # checked baggage
        add("ENTER Baggage Drop", 2, 4)
        add("LEAVE Baggage Drop", 2, 15)
    elif r0 <= 60:  # desk check-in
        add("ENTER Check-In", 2, 4)
        add("LEAVE Check-In", 2, 15)
    # else: straight to Security (carry-on / online check-in)

    add("ENTER Security Check", 2, 4)
    add("LEAVE Security Check", 4, 30)

    r1 = rng.randint(1, 100)
    node = (
        "passport" if r1 <= 25
        else "dutyfree" if r1 <= 50
        else "dining" if r1 <= 70
        else "lounge" if r1 <= 85
        else "boarding"
    )
    has_passport = False

    guard = 0
    while True:
        guard += 1
        if guard > 100:  # mirrors the source's recursion cap (effectively never hit)
            node = "boarding"

        if node == "passport":
            add("ENTER Passport Control", 2, 10)
            add("LEAVE Passport Control", 2, 10)
            has_passport = True  # everything after is the international ("Int") side
            r = rng.randint(1, 100)
            node = "dutyfree" if r <= 35 else "dining" if r <= 50 else "lounge" if r <= 75 else "boarding"
        elif node == "dutyfree":
            sfx = "Int" if has_passport else "Dom"
            add(f"ENTER Duty Free {sfx}", 2, 6)
            add(f"LEAVE Duty Free {sfx}", 5, 30)
            r = rng.randint(1, 100)
            node = "lounge" if r <= 20 else "dining" if r <= 55 else "boarding"
        elif node == "lounge":
            sfx = "Int" if has_passport else "Dom"
            add(f"ENTER Lounge {sfx}", 2, 10)
            add(f"LEAVE Lounge {sfx}", 2, 10)
            r = rng.randint(1, 100)
            node = "dutyfree" if r <= 20 else "dining" if r <= 45 else "boarding"
        elif node == "dining":
            sfx = "Int" if has_passport else "Dom"
            add(f"ENTER Dining Area {sfx}", 2, 10)
            add(f"LEAVE Dining Area {sfx}", 2, 10)
            r = rng.randint(1, 100)
            node = "dutyfree" if r <= 20 else "lounge" if r <= 35 else "boarding"
        else:  # boarding
            sfx = "Int" if has_passport else "Dom"
            add(f"ENTER Boarding Gate {sfx}", 2, 10)
            if rng.randint(1, 100) <= 5:
                add(f"DENIED Boarding {sfx}", 2, 10)
            else:
                add(f"BOARD Aircraft {sfx}", 2, 10)
            return rows


def _airport_journey_at(index: int, rng: random.Random) -> list[JEvent]:
    # EVENT_ID = MD5 of "APF-<7-digit sequence>" — deterministic and unique per journey.
    return _generate_airport_journey(_md5_id("APF-%07d" % (index + 1)), rng)


def generate_airport_rows(count: int, rng: random.Random | None = None) -> list[JEvent]:
    rng = rng or random.Random()
    rows: list[JEvent] = []
    for i in range(count):
        rows.extend(_airport_journey_at(i, rng))
    return rows


# ── dataset registry ──────────────────────────────────────────────────────────

DATASETS: dict[str, DemoDataset] = {
    "retail": DemoDataset(
        key="retail",
        title_short="BOOKSTORE",
        title="Online Bookstore",
        description=(
            "End-to-end order flow: login, browse, basket, checkout, payment, fulfilment, "
            "delivery, returns. Bank Transfer has known payment reliability issues."
        ),
        meta_titles=("Payment Method", "Customer Segment", "Order Value"),
        step_defs=_RETAIL_STEP_DEFS,
        generate=generate_retail_rows,
    ),
    "finance": DemoDataset(
        key="finance",
        title_short="CREDIT",
        title="Online Credit Application",
        description=(
            "Bank/affiliate intake, application check with a rework loop, credit "
            "assessment, then score- and sum-driven approval with agent-review loops — "
            "ending in acceptance and payment, or rejection."
        ),
        meta_titles=("Applied Credit Sum", "Income Class", "Channel"),
        step_defs=_FINANCE_STEP_DEFS,
        generate=generate_finance_rows,
    ),
    "transportation": DemoDataset(
        key="transportation",
        title_short="FLIGHTS",
        title="Flight Booking & Management",
        description=(
            "Star Alliance-style flight booking: login, search with a modify loop, "
            "flight selection, booking and payment (Credit Card, SEPA, Apple Pay, "
            "Google Pay, Advance Payment). 50% of bookings are interline (multi-airline) "
            "and query a partner airline's system; 20% only manage an existing booking "
            "(seat reservation / ancillary services)."
        ),
        meta_titles=("Journey Type", "Airline", "Payment Method"),
        step_defs=_TRANSPORT_STEP_DEFS,
        generate=generate_transportation_rows,
    ),
    "airport": DemoDataset(
        key="airport",
        title_short="APF",
        title="Airport Passenger Flow",
        description=(
            "A departing passenger's walk through the terminal: departure hall, baggage "
            "drop / check-in, security, then the airside amenities (duty free, lounge, "
            "dining) in any order before boarding. Passport Control switches the airside "
            "and boarding steps from their domestic (Dom) to their international (Int) "
            "variant; 2% leave the hall without travelling and 5% of boardings are denied."
        ),
        meta_titles=("Terminal", "-", "-"),
        step_defs=_AIRPORT_STEP_DEFS,
        generate=generate_airport_rows,
        generate_one=_airport_journey_at,  # streamed → supports up to 1,000,000+ journeys
    ),
}


# ── SQL builders ──────────────────────────────────────────────────────────────


def _sq(value: str) -> str:
    return value.replace("'", "''")


def step_id_map(step_defs: list[StepDef]) -> dict[str, int]:
    """Stable per-activity id for each step name — its 1-based position in the
    dataset's step list. JOURNEYS.STEP_ID and STEPS.STEP_ID both carry this id so
    the transition query groups/joins on an integer instead of the step name."""
    return {sd[0]: i + 1 for i, sd in enumerate(step_defs)}


def _insert_steps_sqls(step_defs: list[StepDef], project_id: str) -> list[str]:
    # Insert each step only if it doesn't already exist, so operator customisations
    # (colours, shapes, scores set via the Step editor) are preserved.
    out: list[str] = []
    for idx, (name, desc, bg, fg, score, shape, eop, group) in enumerate(step_defs):
        step_id = idx + 1  # stable activity id (matches step_id_map)
        eop_sql = "TRUE" if eop else "FALSE"
        out.append(
            "INSERT INTO STEPS (PROJECT_ID, STEP, STEP_ID, DESCRIPTION, BG_COLOR, FG_COLOR, SCORE, "
            "SHAPE, END_OF_PROCESS, BELONGS_TO) "
            f"SELECT {int(project_id)}, '{_sq(name)}', {step_id}, '{_sq(desc)}', '{bg}', '{fg}', "
            f"{score}, '{shape}', {eop_sql}, '{_sq(group)}' "
            f"WHERE NOT EXISTS (SELECT 1 FROM STEPS WHERE PROJECT_ID = {int(project_id)} "
            f"AND STEP = '{_sq(name)}')"
        )
    return out


def _insert_journeys_sql(rows: list[JEvent], project_id: str) -> str:
    vals = ",\n  ".join(
        f"({int(project_id)}, '{_sq(r.event_id)}', '{_sq(r.step)}', {r.step_id}, "
        f"TIMESTAMP '{r.event_time:%Y-%m-%d %H:%M:%S}', '{_sq(r.meta1)}', '{_sq(r.meta2)}', "
        f"'{_sq(r.meta3)}')"
        for r in rows
    )
    return (
        "INSERT INTO JOURNEYS (PROJECT_ID, EVENT_ID, STEP, STEP_ID, EVENT_TIME, "
        f"META_1, META_2, META_3) VALUES\n  {vals}"
    )


async def generate_demo_content(
    *,
    dataset: str,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str,
    journeys: int,
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> dict:
    """Provision the schema + tables and load ``journeys`` journeys of ``dataset``.

    Returns ``{ok, error, journeys, project, dataset, message}``. Idempotent for
    reference data (steps only added if missing); the dataset's own JOURNEYS are
    replaced. Only the dataset's project rows are touched.
    """
    import asyncio

    from ..models import DatabaseServer
    from .manager import DatabaseManager, friendly_error
    from .schema_ddl import PROCESS_MINING_TABLES, _quote_ident

    spec = DATASETS.get((dataset or "retail").strip().lower())
    if spec is None:
        return {"ok": False, "error": f"Unknown demo dataset '{dataset}'.", "journeys": 0}

    schema = (schema or "").strip()
    if not schema:
        return {"ok": False, "error": "A schema name is required.", "journeys": 0}
    try:
        count = int(journeys)
    except (TypeError, ValueError):
        count = 0
    if count < 1:
        return {"ok": False, "error": "Enter how many journeys to generate.", "journeys": 0}
    # Streamed datasets carry a per-journey generator, so they can go far higher than
    # the in-memory ceiling without holding every event in memory at once.
    count = min(count, MAX_JOURNEYS_STREAMED if spec.generate_one else MAX_JOURNEYS)

    server = DatabaseServer(
        id="demo",
        host=host,
        port=port,
        username=username,
        useTLS=use_tls,
        certModeRaw=cert_mode,
        fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits,
        **{"schema": ""},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)
    ident = _quote_ident(schema)
    short = spec.title_short  # the human code (e.g. "CREDIT"); PROJECT_ID is allocated

    def _run() -> None:
        conn = mgr._open(server, password)
        try:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {ident}")
            conn.execute(f"OPEN SCHEMA {ident}")
            for _name, ddl in PROCESS_MINING_TABLES:
                conn.execute(ddl)
            # Idempotent by the TITLE_SHORT code: reuse this demo project's id if it
            # already exists, else allocate the next free SMALLINT.
            row = conn.execute(
                f"SELECT PROJECT_ID FROM PROJECTS WHERE TITLE_SHORT = '{_sq(short)}'"
            ).fetchall()
            if row:
                pid = int(row[0][0])
            else:
                mx = conn.execute("SELECT COALESCE(MAX(PROJECT_ID), 0) FROM PROJECTS").fetchval()
                pid = int(mx or 0) + 1
            conn.execute(f"DELETE FROM PROJECTS WHERE PROJECT_ID = {pid}")
            conn.execute(
                "INSERT INTO PROJECTS (PROJECT_ID, TITLE, DESCRIPTION, TITLE_SHORT) VALUES "
                f"({pid}, '{_sq(spec.title)}', '{_sq(spec.description)}', '{_sq(short)}')"
            )
            conn.execute(f"DELETE FROM METAS WHERE PROJECT_ID = {pid}")
            conn.execute(
                "INSERT INTO METAS (PROJECT_ID, META_1_TITLE, META_2_TITLE, META_3_TITLE) "
                f"VALUES ({pid}, '{_sq(spec.meta_titles[0])}', "
                f"'{_sq(spec.meta_titles[1])}', '{_sq(spec.meta_titles[2])}')"
            )
            for sql in _insert_steps_sqls(spec.step_defs, pid):
                conn.execute(sql)
            conn.execute(f"DELETE FROM JOURNEYS WHERE PROJECT_ID = {pid}")
            rng = random.Random()
            if spec.generate_one is not None:
                # Streamed: build one journey at a time and flush in row-batches, so
                # memory stays flat regardless of the journey count.
                buffer: list[JEvent] = []
                for i in range(count):
                    buffer.extend(spec.generate_one(i, rng))
                    if len(buffer) >= _STREAM_BATCH_ROWS:
                        conn.execute(_insert_journeys_sql(buffer, pid))
                        buffer = []
                if buffer:
                    conn.execute(_insert_journeys_sql(buffer, pid))
            else:
                rows = spec.generate(count, rng)
                for offset in range(0, len(rows), _BATCH_SIZE):
                    conn.execute(_insert_journeys_sql(rows[offset : offset + _BATCH_SIZE], pid))
            conn.commit()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": friendly_error(exc), "journeys": 0}
    return {
        "ok": True,
        "error": None,
        "journeys": count,
        "project": spec.title,
        "dataset": spec.key,
        "message": f"Created {count} journeys for “{spec.title}” in {schema}.JOURNEYS",
    }
