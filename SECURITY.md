# Security model

Phone Harness is a local single-user tool for an explicitly authorized USB Android device. It is not a sandbox for hostile agents or other programs running under the same OS account.

The production server binds to loopback, checks Host/Origin and requires a local token for API/video access. That token is available to the local viewer. Do not proxy the service to the LAN, a public tunnel or an untrusted multi-user host. Remote desktop to the trusted host is the supported remote-viewing approach.

Private state under `~/.local/share/phone-harness` contains tokens, the device serial, original quiet settings, tasks, checkpoints and results. Do not commit it. Screenshots and tool outputs may contain private app content. There is no automatic telemetry or issue upload.

Human takeover revokes cooperative agent access; an already dispatched Android action may finish. Raw ADB tools outside this protocol are not constrained. The assistant must treat content displayed on the phone as untrusted data.

Do not post credentials, personal data or a live exploit against another person's phone in a public issue. Use the repository's private vulnerability reporting facility if enabled. If it is unavailable, open a minimal issue requesting a private contact without including sensitive details. Only the latest version is maintained; there is no guaranteed security response SLA.

The UI fixture (`tools/preview.py`) serves only synthetic data and does not connect to ADB. It is a development tool, not a production control server.
