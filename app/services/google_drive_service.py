import os
import io
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Define the scopes for Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service_for_user(refresh_token: str = None):
    """
    Authenticates and returns a Google Drive service object using a Centralized OAuth Refresh Token
    for uploading to the 5TB Admin Google Drive.
    """
    client_id = os.getenv("GOOGLE_ADMIN_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_ADMIN_CLIENT_SECRET")
    admin_refresh_token = os.getenv("GOOGLE_ADMIN_REFRESH_TOKEN")
    
    if not all([client_id, client_secret, admin_refresh_token]):
        raise ValueError("Missing GOOGLE_ADMIN_CLIENT_ID, GOOGLE_ADMIN_CLIENT_SECRET, or GOOGLE_ADMIN_REFRESH_TOKEN in environment variables.")

    creds = Credentials(
        token=None,
        refresh_token=admin_refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES
    )
    
    service = build('drive', 'v3', credentials=creds)
    return service

def get_or_create_climbup_folder(service) -> str:
    """Finds or creates a 'ClimbUP' folder, or uses a specific FOLDER_ID if provided."""
    
    # Best approach: Use a specific folder ID shared with the Service Account or Admin Account
    specific_folder_id = os.environ.get("TARGET_FOLDER_ID")
    if specific_folder_id:
        return specific_folder_id

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

def download_file_from_drive(refresh_token: str, file_id: str) -> bytes:
    """
    Downloads a file from the user's personal Google Drive into memory.
    Returns the raw bytes of the file.
    """
    service = get_drive_service_for_user(refresh_token)
    
    # Check file size first to prevent Render OOM (max 15MB)
    file_metadata = service.files().get(fileId=file_id, fields="size").execute()
    file_size_bytes = int(file_metadata.get('size', 0))
    if file_size_bytes > 15 * 1024 * 1024:
        raise Exception(f"File is too large ({file_size_bytes / (1024*1024):.1f} MB) to download directly to WhatsApp.")

    # Download file content
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        
    return fh.getvalue()
