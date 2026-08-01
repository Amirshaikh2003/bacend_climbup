import os
import io
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Define the scopes for Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service_for_user(refresh_token: str):
    """
    Authenticates and returns a Google Drive service object for a specific user 
    using their refresh token.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES
    )
    
    # This will automatically refresh the token when making the first request
    service = build('drive', 'v3', credentials=creds)
    return service

def get_or_create_climbup_folder(service) -> str:
    """Finds or creates a 'ClimbUP' folder in the user's drive and returns its ID."""
    folder_name = "ClimbUP"
    # Search for the folder
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    items = results.get('files', [])
    
    if not items:
        # Create folder
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')
    return items[0].get('id')

def upload_file_to_user_drive(refresh_token: str, file_bytes: bytes, filename: str, mime_type: str = 'application/pdf') -> str:
    """
    Uploads a file to the user's personal Google Drive in the ClimbUP folder.
    Returns the public web view URL.
    """
    service = get_drive_service_for_user(refresh_token)
    
    # 1. Get or Create "ClimbUP" Folder
    folder_id = get_or_create_climbup_folder(service)
    
    # 2. Multipart Upload
    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    
    file = service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id, webViewLink'
    ).execute()
    
    file_id = file.get('id')
    
    # 3. Automatic Public Permission
    try:
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        service.permissions().create(
            fileId=file_id,
            body=permission,
            fields='id'
        ).execute()
    except Exception as e:
        # Fallback if organization restricts public sharing
        service.files().delete(fileId=file_id).execute()
        raise PermissionError(f"Could not make file public. Make sure you are using a personal Gmail account. Error: {str(e)}")
    
    return file.get('webViewLink')

