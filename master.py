import msal

app = msal.ConfidentialClientApplication(
    "e96d9338-9d3e-4733-98cd-d2d600f45abf",
    client_credential="ZZw8Q~S6e_oKWvIBTyde7kAUURJCCeNf2zTLxcs2",
    authority="https://login.microsoftonline.com/aadc5d1f-19d3-4ced-a0e5-0aae419ec4d2"
)

result = app.acquire_token_for_client(
    scopes=["https://graph.microsoft.com/.default"]
)

access_token = result.get("access_token")
print(access_token)
