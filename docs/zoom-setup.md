# Zoom authorization

Create a User-managed General App in Zoom App Marketplace and enable Features > Embed > Meeting SDK. Use its Meeting SDK Client ID/Secret, not Server-to-Server OAuth credentials. Administrators may need to enable Zoom for developers and SDK View/Edit permissions.

Begin with a meeting hosted by the app-owning account. External-account meetings may require review/publication and additional authorization. Successful SDK authentication does not establish permission to join every meeting.

- [SDK credentials](https://developers.zoom.us/docs/meeting-sdk/get-credentials/)
- [SDK authentication](https://developers.zoom.us/docs/meeting-sdk/auth/)
- [General App prerequisites](https://developers.zoom.us/docs/build-flow/create-oauth-apps/#prerequisites)

The main voice path reads .env; see [configuration](manual-setup.md). An optional auth diagnostic uses separate ignored config/zoom.local.json:

~~~bash
python3 scripts/zoom_config.py init
# Fill in config/zoom.local.json locally.
python3 scripts/zoom_config.py check
python3 scripts/zoom_config.py token
python3 scripts/zoom_macos_auth.py --sdk /absolute/path/to/extracted-sdk
~~~

Init does not overwrite existing configuration. Check validates fields. Token saves a private native SDK JWT to .runtime/zoom-sdk.jwt without printing it; it is not an OAuth token. The macOS probe authenticates only; add --join for a bounded connection test with audio/video disabled.

Authentication, join-request acceptance, InMeeting, raw-audio permission, non-silent input, full outgoing speech and remote artifact visibility are distinct observations. Handle Keychain authorization through macOS, never by putting a device password in logs or configuration.
