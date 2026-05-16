# Google Sign-Up Setup

Google sign-up uses Streamlit's built-in OpenID Connect flow through `st.login("google")`.
Configuration belongs in Streamlit secrets, not in committed code.

## Local Development

1. Install dependencies and restart Streamlit:

```bash
python -m pip install -r requirements.txt
python -m streamlit run reminders_app_v3.py
```

2. Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml`.

3. Generate a cookie secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

4. Set `redirect_uri` to the exact local address you use in the browser:

```toml
[auth]
redirect_uri = "http://127.0.0.1:8501/oauth2callback"
cookie_secret = "paste-generated-secret-here"

[auth.google]
client_id = "your-google-client-id.apps.googleusercontent.com"
client_secret = "your-google-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Use `http://localhost:8501/oauth2callback` instead if you open the app at `localhost`.
Do not mix `localhost` and `127.0.0.1`; Google treats them as different redirect URLs.

## Google Cloud

1. In Google Cloud Console, create or open the app's OAuth project.
2. Configure the consent screen under Google Auth Platform > Branding.
3. While testing, add your Google account under Audience > Test users.
4. Create an OAuth client with application type `Web application`.
5. Add every callback URL the app will use under Authorized redirect URIs:

```text
http://127.0.0.1:8501/oauth2callback
http://localhost:8501/oauth2callback
https://your-dev-streamlit-app.streamlit.app/oauth2callback
https://your-production-streamlit-app.streamlit.app/oauth2callback
```

Only add URLs you actually use. The value in `.streamlit/secrets.toml` or Streamlit
Cloud secrets must match one of these exactly.

## Streamlit Cloud

Put the same TOML in the app's Streamlit Cloud secrets. For the dev app, use the dev
app URL in `redirect_uri`; for production, use the production app URL.

Streamlit Community Cloud may route hosted auth through a prefixed callback path such
as:

```text
https://your-dev-streamlit-app.streamlit.app/-/+/oauth2callback
```

If the browser returns to that path after Google sign-in and logs show
`MismatchingStateError`, use that exact callback path in both places:

- Streamlit Cloud secrets: `[auth].redirect_uri`
- Google Cloud OAuth client: Authorized redirect URIs

Keep Authorized JavaScript origins as the app origin only, without a path:

```text
https://your-dev-streamlit-app.streamlit.app
```

## If The Callback Shows `ERR_EMPTY_RESPONSE`

Check these first:

- The Streamlit process is still running.
- `Authlib` is installed: `python -m pip install -r requirements.txt`.
- The callback URL in the browser exactly matches `redirect_uri`.
- The same callback URL is listed in Google Cloud Authorized redirect URIs.
- Streamlit was restarted after editing secrets.

## If Logs Show `MismatchingStateError`

Check these first:

- The Streamlit Cloud callback path in `[auth].redirect_uri` exactly matches the
  callback path in the browser address bar before the `?state=...` query string.
- The same exact callback path is listed in Google Cloud Authorized redirect URIs.
- You started from the app's base URL and did not refresh, duplicate, or reuse an old
  auth callback tab.
- Streamlit was rebooted after editing secrets.
