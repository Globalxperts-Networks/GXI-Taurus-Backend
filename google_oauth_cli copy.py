#!/usr/bin/env python3
import os
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import parse

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# -- CONFIGURATION --
CLIENT_SECRET_FILE = "credentials/client_secret.json"
TOKEN_FILE = "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# This must match the redirect URI already present in your client_secret.json
# (exact match including trailing slash)
REDIRECT_URI = "http://localhost:8000/hiring/google-auth/callback/"

def generate_token():
    creds = None

    # If token exists already (try to load/refresh it)
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                creds = Credentials.from_authorized_user_info(data, SCOPES)
        except Exception as e:
            print(f"⚠️ Could not load existing token: {e}")
            creds = None

    # If no token OR token expired
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("🌐 Starting OAuth flow (will open browser)...")

            # Build the flow from the existing client_secret.json (web client)
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE,
                SCOPES
            )

            # Force the redirect_uri to the one already registered in GCP
            flow.redirect_uri = REDIRECT_URI

            # Request offline access so we receive a refresh token
            auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")

            # Open the browser for the user to authenticate
            print("👉 If the browser does not open automatically, copy this URL and open it manually:\n")
            print(auth_url)
            try:
                webbrowser.open(auth_url, new=1, autoraise=True)
            except Exception:
                pass

            # Prepare a simple HTTP server to receive the OAuth callback
            class _Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    # Only handle the exact callback path
                    parsed = parse.urlsplit(self.path)
                    # path may include the route and query; compare path part
                    if parsed.path != parse.urlsplit(REDIRECT_URI).path:
                        # Not the callback we want; return 404
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"Not found")
                        return

                    qs = parse.parse_qs(parsed.query)
                    error = qs.get("error")
                    if error:
                        # User denied or another error
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        msg = f"Authentication failed: {error}"
                        self.wfile.write(msg.encode("utf-8"))
                        print("❌ OAuth error:", error)
                        return

                    code = qs.get("code", [None])[0]
                    if not code:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"Missing code in callback")
                        print("❌ No code found in the callback.")
                        return

                    try:
                        # Exchange the authorization code for tokens
                        flow.fetch_token(code=code)
                        token_creds = flow.credentials

                        # Save token to file
                        with open(TOKEN_FILE, "w", encoding="utf-8") as tf:
                            tf.write(token_creds.to_json())

                        # Respond to the browser
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(b"<html><body><h1>Authentication successful</h1>"
                                         b"<p>You may close this window and return to the terminal.</p></body></html>")

                        print("✅ Token generated successfully!")
                        print(f"👉 File created: {TOKEN_FILE}")

                    except Exception as exc:
                        self.send_response(500)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(b"Internal server error during token exchange")
                        print("❌ Failed to fetch token:", exc)

                def log_message(self, format, *args):
                    # silence the default HTTP server logging to keep console clean
                    return

            server_address = ("localhost", 8000)
            httpd = HTTPServer(server_address, _Handler)

            try:
                print(f"📡 Waiting for Google OAuth redirect on {REDIRECT_URI} ...")
                # handle_request will process a single request then return
                httpd.handle_request()
            except OSError as oe:
                print(f"❌ Could not start HTTP server on port 8000: {oe}")
                print("👉 Maybe the port is already in use. Stop the process using that port or choose a different one.")
                raise
            finally:
                try:
                    httpd.server_close()
                except Exception:
                    pass

            # After the handler runs, token will be saved inside the handler. Load it.
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    creds = Credentials.from_authorized_user_info(data, SCOPES)

    if creds and creds.valid:
        print("✅ Token is ready to use.")
    else:
        print("❌ Token generation failed.")

    return creds


if __name__ == "__main__":
    print("🚀 Google OAuth CLI Started")
    # If you want a fresh flow, remove the existing token file before running:
    # os.remove(TOKEN_FILE)  # uncomment to force a fresh login
    generate_token()
    print("🎉 Done! Now run your interview scheduler script.")