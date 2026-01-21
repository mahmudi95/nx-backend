"""
Booking Configuration
Define work hours, blackout dates, and abuse prevention rules
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Work hours (24-hour format)
WORK_HOURS = {
    "monday": {"start": "09:00", "end": "17:00"},
    "tuesday": {"start": "09:00", "end": "17:00"},
    "wednesday": {"start": "09:00", "end": "17:00"},
    "thursday": {"start": "09:00", "end": "17:00"},
    "friday": {"start": "09:00", "end": "17:00"},
    "saturday": None,  # Closed
    "sunday": None,    # Closed
}

# Meeting settings
SLOT_DURATION_MINUTES = 30  # 30-minute meetings
BUFFER_BETWEEN_MEETINGS = 0  # Minutes buffer between meetings (optional)

# Booking restrictions
MIN_ADVANCE_HOURS = 24  # Must book at least 24 hours in advance
MAX_ADVANCE_DAYS = 30   # Can't book more than 30 days out
MAX_BOOKINGS_PER_DAY = 8  # Maximum slots available per day

# Blackout dates (holidays, vacations, etc.)
BLACKOUT_DATES = [
    "2026-01-01",  # New Year's Day
    "2026-05-01",  # Labour Day
    "2026-12-25",  # Christmas
    "2026-12-26",  # Boxing Day
]

# Lunch break (optional)
LUNCH_BREAK = {
    "start": "12:00",
    "end": "13:00"
}


def is_working_day(date: datetime) -> bool:
    """Check if date is a working day"""
    day_name = date.strftime("%A").lower()
    return WORK_HOURS.get(day_name) is not None


def get_work_hours_for_day(date: datetime) -> Optional[Dict[str, str]]:
    """Get work hours for specific day"""
    day_name = date.strftime("%A").lower()
    return WORK_HOURS.get(day_name)


def is_blackout_date(date: datetime) -> bool:
    """Check if date is in blackout list"""
    date_str = date.strftime("%Y-%m-%d")
    return date_str in BLACKOUT_DATES


def is_lunch_time(time_str: str) -> bool:
    """Check if time falls in lunch break"""
    if not LUNCH_BREAK:
        return False
    
    return LUNCH_BREAK["start"] <= time_str < LUNCH_BREAK["end"]


def get_time_slots_for_day(date: datetime) -> List[str]:
    """
    Generate all possible time slots for a given day
    Returns list of time strings like ["09:00", "09:30", "10:00", ...]
    """
    # Check if working day
    if not is_working_day(date) or is_blackout_date(date):
        return []
    
    work_hours = get_work_hours_for_day(date)
    if not work_hours:
        return []
    
    # Parse start and end times
    start_time = datetime.strptime(work_hours["start"], "%H:%M")
    end_time = datetime.strptime(work_hours["end"], "%H:%M")
    
    slots = []
    current_time = start_time
    
    while current_time < end_time:
        time_str = current_time.strftime("%H:%M")
        
        # Skip lunch break
        if not is_lunch_time(time_str):
            slots.append(time_str)
        
        current_time += timedelta(minutes=SLOT_DURATION_MINUTES)
    
    return slots


def is_valid_booking_time(booking_datetime: datetime) -> tuple[bool, str]:
    """
    Validate if a booking time is allowed
    Returns (is_valid, error_message)
    """
    now = datetime.now()
    
    # Check minimum advance notice
    min_advance = now + timedelta(hours=MIN_ADVANCE_HOURS)
    if booking_datetime < min_advance:
        return False, f"Bookings must be made at least {MIN_ADVANCE_HOURS} hours in advance"
    
    # Check maximum advance booking
    max_advance = now + timedelta(days=MAX_ADVANCE_DAYS)
    if booking_datetime > max_advance:
        return False, f"Bookings cannot be made more than {MAX_ADVANCE_DAYS} days in advance"
    
    # Check if working day
    if not is_working_day(booking_datetime):
        return False, "Selected day is not available for bookings"
    
    # Check blackout dates
    if is_blackout_date(booking_datetime):
        return False, "Selected date is not available"
    
    # Check work hours
    work_hours = get_work_hours_for_day(booking_datetime)
    if not work_hours:
        return False, "No working hours defined for this day"
    
    time_str = booking_datetime.strftime("%H:%M")
    
    # Check if within work hours
    if not (work_hours["start"] <= time_str < work_hours["end"]):
        return False, f"Selected time is outside working hours ({work_hours['start']} - {work_hours['end']})"
    
    # Check lunch break
    if is_lunch_time(time_str):
        return False, "Selected time falls during lunch break"
    
    return True, ""
