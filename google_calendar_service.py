"""
Google Calendar API Service using Service Account
Creates basic calendar events (no Google Meet auto-generation)
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
from typing import Dict, Any

class GoogleCalendarService:
    def __init__(self):
        self.credentials = None
        self.service = None
        
        service_account_file = os.path.join(os.path.dirname(__file__), 'service-account.json')
        
        if os.path.exists(service_account_file):
            self.credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            self.service = build('calendar', 'v3', credentials=self.credentials)
    
    def create_meeting(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.service:
            return {
                "success": False,
                "error": "Service account not configured"
            }
        
        try:
            meeting_datetime = datetime.strptime(
                f"{form_data['meetingDate']} {form_data['meetingTime']}", 
                "%Y-%m-%d %H:%M"
            )
            end_datetime = meeting_datetime + timedelta(minutes=30)
            
            event = {
                'summary': f'Strategy Call - {form_data["companyName"]}',
                'description': (
                    f"{form_data['email']}\n"
                    f"{form_data['phone']}\n"
                    f"{form_data['role']}\n\n"
                    f"{form_data['goals']}"
                ),
                'start': {
                    'dateTime': meeting_datetime.isoformat(),
                    'timeZone': form_data['timezone'],
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': form_data['timezone'],
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }
            
            created_event = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
            return {
                "success": True,
                "event_id": created_event['id'],
                "event_link": created_event.get('htmlLink'),
                "attendee_email": form_data['email'],
                "message": f"Event created! Manually add Google Meet and invite {form_data['email']}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def is_configured(self) -> bool:
        return self.service is not None


calendar_service = GoogleCalendarService()
