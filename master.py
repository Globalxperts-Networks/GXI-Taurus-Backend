# fetch_teams_chats.py
import msal
import requests
import os

TENANT = os.environ.get("AZURE_TENANT_ID")
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

AUTHORITY = f"https://login.microsoftonline.com/{TENANT}"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

def get_app_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=AUTHORITY,
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise Exception("Failed to acquire token: " + str(result))
    return result["access_token"]

def list_user_chats(user_principal_name):
    token = get_app_token()
    url = f"{GRAPH_BASE}/users/{user_principal_name}/chats"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()   # contains 'value' and maybe '@odata.nextLink'

def list_chat_messages(chat_id, top=50):
    token = get_app_token()
    url = f"{GRAPH_BASE}/chats/{chat_id}/messages?$top={top}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    user = "jai.jha@gxinetworks.com"   # organizer user in your tenant
    chats = list_user_chats(user)
    print("Chats page:", chats.get("value", [])[:3])
    if chats.get("value"):
        first_chat = chats["value"][0]
        chat_id = first_chat["id"]
        print("Fetching messages for chat:", chat_id)
        msgs = list_chat_messages(chat_id, top=25)
        for m in msgs.get("value", [])[:10]:
            print(m.get("from"), m.get("body", {}).get("contentPreview") or m.get("body", {}).get("content"))
