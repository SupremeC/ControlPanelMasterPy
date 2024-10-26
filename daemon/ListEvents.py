from google.oauth2 import service_account
from googleapiclient.discovery import build

# Path to your service account key file
SERVICE_ACCOUNT_FILE = 'axelcpanel-googleServiceAccount_5cbed8cf7a1a.json'

# Define the scopes your application needs access to
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Authenticate with service account credentials
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# If you're impersonating a user, add this:
credentials = credentials.with_subject('axel.berglund.rost@gmail.com')

# Build the Google Calendar service
service = build('calendar', 'v3', credentials=credentials)

# Now you can use the service to access the Google Calendar API
# Example: List events on the primary calendar
events_result = service.events().list(calendarId='primary').execute()
events = events_result.get('items', [])

for event in events:
    print(event['summary'])