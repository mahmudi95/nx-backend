"""
Google Calendar OAuth2 Service
Allows creating events with Google Meet using YOUR Google account
"""

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
import json
from typing import Dict, Any, Optional

# OAuth2 scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Credentials file locations
OAUTH_CREDS_FILE = 'oauth-credentials.json'
TOKEN_FILE = 'token.json'


class GoogleOAuthService:
    def __init__(self):
        self.creds = None
        self.service = None
        self._load_credentials()
    
    def _load_credentials(self):
        """Load saved credentials or None if not authorized yet"""
        token_path = os.path.join(os.path.dirname(__file__), TOKEN_FILE)
        
        if os.path.exists(token_path):
            with open(token_path, 'r') as token:
                creds_data = json.load(token)
                self.creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
            
            # Refresh if expired
            if self.creds and self.creds.expired and self.creds.refresh_token:
                from google.auth.transport.requests import Request
                self.creds.refresh(Request())
                self._save_credentials()
            
            self.service = build('calendar', 'v3', credentials=self.creds)
    
    def _save_credentials(self):
        """Save credentials to file"""
        token_path = os.path.join(os.path.dirname(__file__), TOKEN_FILE)
        with open(token_path, 'w') as token:
            token.write(self.creds.to_json())
    
    def get_auth_url(self, redirect_uri: str = 'http://localhost:8000/auth/callback') -> Optional[str]:
        """Get OAuth2 authorization URL"""
        creds_path = os.path.join(os.path.dirname(__file__), OAUTH_CREDS_FILE)
        
        if not os.path.exists(creds_path):
            print(f"⚠️  {OAUTH_CREDS_FILE} not found")
            print("Download OAuth2 credentials from Google Cloud Console")
            return None
        
        flow = Flow.from_client_secrets_file(
            creds_path,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        return auth_url
    
    def authorize_from_code(self, code: str, redirect_uri: str = 'http://localhost:8000/auth/callback'):
        """Complete OAuth2 flow and save credentials"""
        creds_path = os.path.join(os.path.dirname(__file__), OAUTH_CREDS_FILE)
        
        flow = Flow.from_client_secrets_file(
            creds_path,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        flow.fetch_token(code=code)
        self.creds = flow.credentials
        self._save_credentials()
        self.service = build('calendar', 'v3', credentials=self.creds)
        
        return True
    
    def is_authorized(self) -> bool:
        """Check if we have valid credentials"""
        return self.creds is not None and self.service is not None
    
    def check_conflicts(self, start_time: datetime, end_time: datetime, timezone_str: str) -> bool:
        """Check if there's a conflicting event"""
        try:
            import pytz
            
            # Make timezone-aware
            tz = pytz.timezone(timezone_str)
            start_aware = tz.localize(start_time)
            end_aware = tz.localize(end_time)
            
            # Use dedicated Neuraplex calendar
            calendar_id = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=start_aware.isoformat(),
                timeMax=end_aware.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return len(events) > 0  # True if conflict exists
        except Exception as e:
            print(f"Conflict check error: {e}")
            return False  # If can't check, allow booking
    
    def create_meeting(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create calendar event with Google Meet link
        """
        if not self.is_authorized():
            return {
                "success": False,
                "error": "Not authorized",
                "message": "Please complete OAuth2 setup first"
            }
        
        try:
            # Parse meeting time
            meeting_datetime = datetime.strptime(
                f"{form_data['meetingDate']} {form_data['meetingTime']}", 
                "%Y-%m-%d %H:%M"
            )
            end_datetime = meeting_datetime + timedelta(minutes=30)
            
            # Check for conflicts
            if self.check_conflicts(meeting_datetime, end_datetime, form_data['timezone']):
                return {
                    "success": False,
                    "error": "Time slot not available",
                    "message": f"This time slot is already booked. Please choose another time."
                }
            
            # Client-facing description (minimal - what they see in email)
            client_description = "Looking forward to our strategy call!\n\nJoin via Google Meet (link in calendar event)."
            
            # Full details stored as private note (only YOU see this in YOUR calendar)
            private_notes = (
                f"📋 CLIENT DETAILS\n"
                f"━━━━━━━━━━━━━━\n"
                f"Company: {form_data['companyName']}\n"
                f"Contact: {form_data['fullName']}\n"
                f"Email: {form_data['email']}\n"
                f"Phone: {form_data['phone']}\n"
                f"Role: {form_data['role']}\n"
                f"Industry: {form_data['industry']}\n"
                f"Website: {form_data.get('website', 'N/A')}\n\n"
                f"🎯 GOALS\n{form_data['goals']}\n\n"
                f"📊 Source: {form_data.get('howDidYouHear', 'N/A')}"
            )
            
            # Create event
            event = {
                'summary': f'Strategy Call - {form_data["companyName"]}',
                'description': client_description,
                'extendedProperties': {
                    'private': {
                        'details': private_notes
                    }
                },
                'start': {
                    'dateTime': meeting_datetime.isoformat(),
                    'timeZone': form_data['timezone'],
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': form_data['timezone'],
                },
                'attendees': [
                    {'email': form_data['email']},
                ],
                'conferenceData': {
                    'createRequest': {
                        'requestId': f"neuraplex-{int(datetime.now().timestamp())}",
                        'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                    }
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'email', 'minutes': 60},
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
                'sendUpdates': 'all',
            }
            
            # Use dedicated calendar (Neuraplex) or primary
            calendar_id = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
            
            # Create event
            created_event = self.service.events().insert(
                calendarId=calendar_id,
                body=event,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            
            # Extract Meet link
            meet_link = None
            if 'conferenceData' in created_event:
                entry_points = created_event['conferenceData'].get('entryPoints', [])
                for entry in entry_points:
                    if entry['entryPointType'] == 'video':
                        meet_link = entry['uri']
                        break
            
            return {
                "success": True,
                "event_id": created_event['id'],
                "event_link": created_event.get('htmlLink'),
                "meet_link": meet_link,
                "attendee_email": form_data['email'],
                "message": f"✅ Meeting scheduled with Google Meet! Invite sent to {form_data['email']}"
            }
            
        except Exception as e:
            print(f"Error creating event: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to create meeting"
            }


# Global instance
oauth_service = GoogleOAuthService()
