import os
import json
import requests
from flask import Flask, session, redirect, request, url_for, jsonify, abort
import msal
from urllib.parse import urlencode


# AZURE_TENANT_ID = "aadc5d1f-19d3-4ced-a0e5-0aae419ec4d2"
# AZURE_CLIENT_ID = "e96d9338-9d3e-4733-98cd-d2d600f45abf"
# AZURE_CLIENT_SECRET = "ZZw8Q~S6e_oKWvIBTyde7kAUURJCCeNf2zTLxcs2"

# ---------- CONFIG ----------
# You can also set these as environment variables
CLIENT_ID = "e96d9338-9d3e-4733-98cd-d2d600f45abf"
TENANT_ID =  "aadc5d1f-19d3-4ced-a0e5-0aae419ec4d2"
CLIENT_SECRET = "ZZw8Q~S6e_oKWvIBTyde7kAUURJCCeNf2zTLxcs2"

REDIRECT_PATH = "/getAToken"   # must match Azure redirect URI
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["User.Read", "OnlineMeetings.Read", "OnlineMeetingRecording.Read.All", "Files.Read"]

# Where to save downloaded recordings
DOWNLOAD_FOLDER = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Basic Flask session secret (in prod use a secure random value)
FLASK_SECRET = os.environ.get("FLASK_SECRET", "dev_secret_change_me")

# ---------- END CONFIG ----------

app = Flask(__name__)
app.secret_key = FLASK_SECRET

# MSAL app factory (ConfidentialClientApplication for auth-code flow)
def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=AUTHORITY,
        token_cache=cache
    )

def _build_auth_url(state=None):
    app_msal = _build_msal_app()
    return app_msal.get_authorization_request_url(
        scopes=SCOPES,
        state=state or "state",
        redirect_uri=REDIRECT_URI
    )

def _acquire_token_by_auth_code(auth_code):
    app_msal = _build_msal_app()
    result = app_msal.acquire_token_by_authorization_code(
        auth_code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    return result

def _token_from_session():
    """Return access_token if present and not expired (msal cache not used here)."""
    tok = session.get("token_response")
    if not tok:
        return None
    return tok.get("access_token")

# ---------- Routes ----------

@app.route("/")
def index():
    return "<h3>Teams Recording Fetcher</h3>" \
           "<p>1) <a href='/login'>Login with Microsoft (delegated)</a></p>" \
           "<p>2) After login, call <code>/fetch?meeting_id=&lt;MEETING_ID&gt;</code> to get recording links</p>"

@app.route("/login")
def login():
    auth_url = _build_auth_url(state="12345")
    return redirect(auth_url)

@app.route(REDIRECT_PATH)
def authorized():
    # Called by MS identity platform with code
    error = request.args.get("error")
    if error:
        return f"Error: {error} - {request.args.get('error_description')}", 400

    code = request.args.get("code")
    if not code:
        return "No code received", 400

    result = _acquire_token_by_auth_code(code)
    if "error" in result:
        return f"Token acquisition failed: {result}", 500

    # Save tokens in session - in prod store securely server-side
    session["token_response"] = result
    session["user"] = result.get("id_token_claims", {}).get("preferred_username")
    return f"Login successful for {session.get('user')} — now call /fetch?meeting_id=... or return to <a href='/'>home</a>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

def _call_graph(access_token, method, path, params=None, json_body=None, stream=False):
    url = f"https://graph.microsoft.com/v1.0{path}"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.request(method, url, headers=headers, params=params, json=json_body, stream=stream, timeout=60)
    # Let caller handle HTTP errors; raise for non-2xx
    if resp.status_code >= 400:
        # try to provide helpful info
        try:
            return {"error": resp.json(), "status_code": resp.status_code}
        except Exception:
            return {"error": resp.text, "status_code": resp.status_code}
    return resp

def _extract_recording_info_from_online_meeting(obj):
    """
    Try a few common places for recording info in the onlineMeeting JSON.
    Returns list of dicts: { 'downloadUrl': ..., 'driveItemId': ..., 'description': ... }
    """
    results = []
    # 1) recordings property
    recs = obj.get("recordings") or obj.get("recording") or []
    if isinstance(recs, dict):
        recs = [recs]
    if isinstance(recs, list):
        for r in recs:
            # common keys: contentUrl, downloadUrl, @microsoft.graph.downloadUrl, driveItem (id)
            dl = r.get("contentUrl") or r.get("downloadUrl") or r.get("@microsoft.graph.downloadUrl")
            drive_item = None
            # sometimes stored as resource -> driveItem -> id
            if not dl:
                # inspect nested objects
                if isinstance(r, dict):
                    for k in ("resource", "driveItem", "resourceLocation"):
                        cand = r.get(k) or {}
                        if isinstance(cand, dict):
                            drive_item = cand.get("id") or cand.get("driveItemId") or drive_item
            results.append({"downloadUrl": dl, "driveItemId": drive_item, "raw": r, "note": "from recordings array"})

    # 2) callRecords or resourceLocation fields (sometimes outside recordings)
    # try common keys
    for k in ("callRecords", "recording", "resourceLocation", "recordingAssets"):
        v = obj.get(k)
        if v:
            if isinstance(v, dict):
                dl = v.get("contentUrl") or v.get("downloadUrl") or v.get("@microsoft.graph.downloadUrl")
                if dl:
                    results.append({"downloadUrl": dl, "driveItemId": None, "raw": v, "note": f"from {k}"})
            elif isinstance(v, list):
                for item in v:
                    dl = item.get("contentUrl") or item.get("downloadUrl") or item.get("@microsoft.graph.downloadUrl")
                    results.append({"downloadUrl": dl, "driveItemId": item.get("id"), "raw": item, "note": f"from {k}[list]"})
    # 3) if empty, return empty list
    return results

@app.route("/fetch")
def fetch_meeting():
    """
    Query params:
      meeting_id (required) - the Graph onlineMeeting id (the long string)
      download (optional) - 1 to download first recording found
    """
    meeting_id = request.args.get("meeting_id")
    if not meeting_id:
        return jsonify({"error": "meeting_id required as query param ?meeting_id=<id>"}), 400

    access_token = _token_from_session()
    if not access_token:
        return jsonify({"error": "not authenticated. visit /login and sign in as the organizer first."}), 401

    # call Graph: GET /me/onlineMeetings/{meeting_id}
    path = f"/me/onlineMeetings/{meeting_id}"
    resp = _call_graph(access_token, "GET", path)
    if isinstance(resp, dict) and resp.get("status_code"):
        # error object returned
        return jsonify({"error": "graph_error", "details": resp}), 502

    try:
        om = resp.json()
    except Exception:
        return jsonify({"error": "unable to parse graph response", "raw": resp.text}), 500

    # Attempt to extract recording links
    recs = _extract_recording_info_from_online_meeting(om)
    # If none found, try searching drive for "Recording" items (organizer's drive)
    found = recs.copy()
    if not found:
        # fallback: search user's drive for likely recording files (may be noisy)
        search_path = "/me/drive/root/search(q='Recording')"
        sresp = _call_graph(access_token, "GET", search_path)
        if not (isinstance(sresp, dict) and sresp.get("status_code")):
            try:
                j = sresp.json()
                for it in j.get("value", []):
                    dl = it.get("@microsoft.graph.downloadUrl")
                    if dl:
                        found.append({"downloadUrl": dl, "driveItemId": it.get("id"), "raw": it, "note": "from drive search"})
            except Exception:
                pass

    result = {
        "meeting": om,
        "recordings_found": found
    }

    # If download requested, attempt to download the first found recording
    download_flag = request.args.get("download", "0") in ("1", "true", "yes")
    if download_flag and found:
        first = found[0]
        dl = first.get("downloadUrl")
        drive_item = first.get("driveItemId")
        out_info = {}
        if dl:
            # pre-authenticated download URL -> fetch directly
            r = requests.get(dl, stream=True, timeout=60)
            if r.status_code >= 400:
                out_info["download_error"] = {"status": r.status_code, "text": r.text}
            else:
                # save to file
                filename = f"recording_{meeting_id[:8]}.bin"
                out_path = os.path.join(DOWNLOAD_FOLDER, filename)
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64*1024):
                        if chunk:
                            f.write(chunk)
                out_info["downloaded_to"] = out_path
                out_info["content_type"] = r.headers.get("Content-Type")
                out_info["size"] = os.path.getsize(out_path)
        elif drive_item:
            # use Graph drive content endpoint with delegated token
            drive_path = f"/me/drive/items/{drive_item}/content"
            file_resp = _call_graph(access_token, "GET", drive_path, stream=True)
            if isinstance(file_resp, dict) and file_resp.get("status_code"):
                out_info["download_error"] = file_resp
            else:
                filename = f"recording_{meeting_id[:8]}.bin"
                out_path = os.path.join(DOWNLOAD_FOLDER, filename)
                with open(out_path, "wb") as f:
                    for chunk in file_resp.iter_content(chunk_size=64*1024):
                        if chunk:
                            f.write(chunk)
                out_info["downloaded_to"] = out_path
                out_info["content_type"] = file_resp.headers.get("Content-Type")
                out_info["size"] = os.path.getsize(out_path)
        else:
            out_info["error"] = "no_downloadable_link_found"
        result["download_attempt"] = out_info

    return jsonify(result)

# Simple health route
@app.route("/whoami")
def whoami():
    user = session.get("user")
    return jsonify({"user": user, "authenticated": bool(session.get("token_response"))})

if __name__ == "__main__":
    # Basic safety: ensure config provided
    missing = []
    for k,v in (("CLIENT_ID", CLIENT_ID), ("CLIENT_SECRET", CLIENT_SECRET), ("TENANT_ID", TENANT_ID)):
        if not v or v.startswith("<YOUR_"):
            missing.append(k)
    if missing:
        print("Please set the Azure AD config at top of the script or via environment variables for:", missing)
        print("Edit the script or set AZ_CLIENT_ID, AZ_CLIENT_SECRET, AZ_TENANT_ID env vars.")
        exit(1)

    app.run(host="0.0.0.0", port=5000, debug=True)
