from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
from google_calendar_service import calendar_service
from google_oauth_service import oauth_service
from booking_config import (
    get_time_slots_for_day,
    is_valid_booking_time,
    MIN_ADVANCE_HOURS,
    MAX_ADVANCE_DAYS,
    SLOT_DURATION_MINUTES
)

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class BookingRequest(BaseModel):
    """Form data from get-started page"""
    companyName: str
    companySize: str
    industry: str
    website: Optional[str] = ""
    fullName: str
    email: EmailStr
    phone: str
    role: str
    meetingDate: str  # YYYY-MM-DD
    meetingTime: str  # HH:MM
    timezone: str
    goals: str
    howDidYouHear: Optional[str] = ""


@app.get("/")
async def root():
    return {"message": "Neuraplex API"}


@app.get("/api/status")
async def status():
    service_account_configured = calendar_service.is_configured()
    oauth_authorized = oauth_service.is_authorized()
    return {
        "status": "ok",
        "service": "neuraplex",
        "service_account": "configured" if service_account_configured else "not configured",
        "oauth2": "authorized" if oauth_authorized else "not authorized",
        "google_meet": "enabled" if oauth_authorized else "disabled (needs OAuth2)"
    }


@app.get("/auth/login")
async def auth_login():
    """Start OAuth2 flow"""
    auth_url = oauth_service.get_auth_url()
    
    if not auth_url:
        return HTMLResponse("""
            <h1>⚠️ OAuth2 Not Configured</h1>
            <p>Please add <code>oauth-credentials.json</code> to the backend folder.</p>
            <p>See <code>OAUTH2_SETUP.md</code> for instructions.</p>
        """, status_code=500)
    
    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def auth_callback(code: str):
    """Handle OAuth2 callback"""
    try:
        oauth_service.authorize_from_code(code)
        return HTMLResponse("""
            <h1>✅ Authorization Successful!</h1>
            <p>Google Calendar is now connected with full Google Meet support.</p>
            <p>You can close this window.</p>
            <script>setTimeout(() => window.close(), 3000);</script>
        """)
    except Exception as e:
        return HTMLResponse(f"""
            <h1>❌ Authorization Failed</h1>
            <p>Error: {str(e)}</p>
            <p><a href="/auth/login">Try again</a></p>
        """, status_code=500)


@app.get("/api/calendars")
async def list_calendars():
    """List all available calendars"""
    if not oauth_service.is_authorized():
        raise HTTPException(status_code=401, detail="Not authorized")
    
    try:
        calendars_result = oauth_service.service.calendarList().list().execute()
        calendars = calendars_result.get('items', [])
        
        return {
            "calendars": [
                {
                    "name": cal['summary'],
                    "id": cal['id'],
                    "primary": cal.get('primary', False)
                }
                for cal in calendars
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/available-slots")
async def get_available_slots(start_date: Optional[str] = None, days: int = 14):
    """
    Get available time slots
    Query params:
      - start_date: YYYY-MM-DD (default: tomorrow)
      - days: number of days to check (default: 14, max: 30)
    """
    if not oauth_service.is_authorized():
        raise HTTPException(
            status_code=503,
            detail="Calendar not configured"
        )
    
    # Parse start date or use tomorrow
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        # Start from tomorrow (respect MIN_ADVANCE_HOURS)
        start = datetime.now() + timedelta(hours=MIN_ADVANCE_HOURS)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Limit days range
    days = min(days, MAX_ADVANCE_DAYS)
    
    available_slots = {}
    
    for day_offset in range(days):
        check_date = start + timedelta(days=day_offset)
        date_str = check_date.strftime("%Y-%m-%d")
        
        # Get all possible slots for this day
        possible_slots = get_time_slots_for_day(check_date)
        
        if not possible_slots:
            continue
        
        # Check which slots are free (not booked in calendar)
        free_slots = []
        
        for time_slot in possible_slots:
            # Create datetime for this slot
            slot_datetime = datetime.strptime(f"{date_str} {time_slot}", "%Y-%m-%d %H:%M")
            
            # Skip if in the past
            if slot_datetime < datetime.now():
                continue
            
            # Check if slot conflicts with existing booking
            slot_end = slot_datetime + timedelta(minutes=SLOT_DURATION_MINUTES)
            
            if not oauth_service.check_conflicts(slot_datetime, slot_end, "Europe/Luxembourg"):
                free_slots.append(time_slot)
        
        if free_slots:
            available_slots[date_str] = free_slots
    
    return {
        "available_slots": available_slots,
        "slot_duration_minutes": SLOT_DURATION_MINUTES,
        "timezone": "Europe/Luxembourg"
    }


@app.post("/api/book-meeting")
async def book_meeting(booking: BookingRequest):
    """
    Create a Google Calendar event with Google Meet link
    Uses OAuth2 if authorized (full features) or Service Account (limited)
    """
    # Convert Pydantic model to dict
    form_data = booking.dict()
    
    # Validate booking time against rules
    booking_datetime = datetime.strptime(
        f"{form_data['meetingDate']} {form_data['meetingTime']}",
        "%Y-%m-%d %H:%M"
    )
    
    is_valid, error_message = is_valid_booking_time(booking_datetime)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=error_message
        )
    
    # Try OAuth2 first (has Google Meet support)
    if oauth_service.is_authorized():
        result = oauth_service.create_meeting(form_data)
    # Fall back to service account (no Google Meet)
    elif calendar_service.is_configured():
        result = calendar_service.create_meeting(form_data)
    else:
        raise HTTPException(
            status_code=503,
            detail="Google Calendar not configured. Set up OAuth2 or Service Account."
        )
    
    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to create meeting")
        )
    
    return {
        "success": True,
        "message": result["message"],
        "event_id": result["event_id"],
        "event_link": result["event_link"],
        "meet_link": result.get("meet_link"),
        "attendee_email": result.get("attendee_email")
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
