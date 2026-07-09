"""Administrative reporting and export endpoints."""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..errors import AppError
from ..models import Booking, Room, User
from ..services.export import generate_export
from ..timeutils import parse_input_datetime

router = APIRouter(prefix="/admin", tags=["admin"])


def _parse_report_bound(value: str, is_end: bool) -> tuple[datetime, bool]:
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return parse_input_datetime(value), True
    if is_end:
        return datetime.combine(day + timedelta(days=1), time.min), False
    return datetime.combine(day, time.min), True


@router.get("/usage-report")
def usage_report(
    frm: str = Query(..., alias="from"),
    to: str = Query(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        range_start, _ = _parse_report_bound(frm, False)
        range_end, include_end = _parse_report_bound(to, True)
    except ValueError:
        raise AppError(400, "INVALID_BOOKING_WINDOW", "Invalid date range")

    rooms = db.query(Room).filter(Room.org_id == admin.org_id).order_by(Room.id.asc()).all()
    room_rows = []
    for room in rooms:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.room_id == room.id,
                Booking.status == "confirmed",
                Booking.start_time >= range_start,
                Booking.start_time <= range_end if include_end else Booking.start_time < range_end,
            )
            .all()
        )
        room_rows.append(
            {
                "room_id": room.id,
                "room_name": room.name,
                "confirmed_bookings": len(bookings),
                "revenue_cents": sum(b.price_cents for b in bookings),
            }
        )

    result = {"from": frm, "to": to, "rooms": room_rows}
    return result


@router.get("/export")
def export(
    room_id: int | None = Query(None),
    include_all: bool = Query(False),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if room_id is not None:
        room = db.query(Room).filter(Room.id == room_id, Room.org_id == admin.org_id).first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
    csv_body = generate_export(db, admin.org_id, admin.id, room_id, include_all)
    return Response(content=csv_body, media_type="text/csv")
