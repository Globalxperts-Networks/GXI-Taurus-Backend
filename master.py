import msal
# app = msal.ConfidentialClientApplication(
#     "e96d9338-9d3e-4733-98cd-d2d600f45abf",
#     client_credential="ZZw8Q~S6e_oKWvIBTyde7kAUURJCCeNf2zTLxcs2",
#     authority="https://login.microsoftonline.com/aadc5d1f-19d3-4ced-a0e5-0aae419ec4d2"
# )

# result = app.acquire_token_for_client(
#     scopes=["https://graph.microsoft.com/.default"]
# )


app = msal.ConfidentialClientApplication(
    "bb5aa073-9901-4f94-8935-dc3aa37b5855",
    client_credential="LGO8Q~d25oEUUV8RifOn.G03ryFxN8M6BkU0ddec",
    authority="https://login.microsoftonline.com/b6bc0503-84d4-4cab-9502-058795a1a3ce"
)

result = app.acquire_token_for_client(
    scopes=["https://graph.microsoft.com/.default"]
)

access_token = result.get("access_token")
print(access_token)
