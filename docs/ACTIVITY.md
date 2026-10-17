# Activity records and personal notifications (0.8 preview)

The small waveform icon opens activity records. Enabling recording creates local metadata-only summaries: source, timestamp, gesture category and count. It does not capture text, coordinates, screenshots, audio, foreground applications or the meaning of a clicked button. Console inputs mean **issued**, not necessarily successfully applied.

`human` means the console's manual input channel (including a remote desktop user); `agent` means the leased task's input channel. Neither identifies a person. `device` means an event from a selected kernel input node. Before physical calibration the UI labels these events as unverified, and external-operation notifications are blocked.

## Input detection

The connected console owns the existing shared device lock. It discovers input capabilities using read-only `getevent -pl`, reads platform topology where available, excludes known virtual/external devices, and starts a bounded set of `getevent -lt` readers. It never runs `su`, changes permissions, writes kernel input events, reads arbitrary keyboard keys, or kills the shared ADB service.

Some OEMs allow `getevent` while denying `/proc/bus/input/devices` and sysfs topology. In that case direct multitouch devices and named built-in key candidates may be observed for calibration, but their physical provenance is **not** asserted. The current G100 has this limitation. Primary-touch gestures are summarized; multi-finger gestures and meaning inside apps are not reconstructed.

A dropped event or dead reader invalidates monitoring. Closing/disconnecting the phone session stops readers. Reconnection re-enumerates nodes; changing the node fingerprint invalidates calibration. USB disconnection or Mac sleep is a coverage gap, not proof of no activity.

## Merging and notifications

- Actions from the same source and remote-idle context merge when separated by no more than 30 seconds.
- For a calibrated device event, the first notification waits 10 seconds to combine initial activity. It contains counts **as of sending**, not a promise that the activity is over.
- A continuous session sends at most once; notifications across sessions have a 5-minute cooldown. Events inside the cooldown remain local.
- Events during a running Agent task, an in-flight phone operation, a held remote pointer, or within 3 seconds of manual remote input are recorded without alerting.
- Missing calibration, unavailable monitoring, failed configuration and stale events do not become alerts later. Historical events are never retroactively notified when calibration is enabled.
- A send with an unknown outcome is never automatically replayed. The notification hook also receives a stable event ID for deduplication.

The private state directory contains `activity.json` (recent 250 summaries, 100 exposed to the UI), `activity-events.jsonl` (append-only metadata journal), optional `activity-notifications.json`, and `activity-validation.json`. Files are private; the journal is not silently deleted or rotated. Its disk usage should be considered for long unattended deployments.

## Connect a personal notification channel

This preview supports a private executable hook rather than shipping account credentials. Configure `activity-notifications.json` inside the state directory, mode `0600`:

```json
{"command":["/absolute/path/to/your-notifier","--profile","your-personal-route"]}
```

The console appends `--event-id <stable-id> --title <title>`, writes plain message text to stdin, and waits at most 30 seconds. No shell is involved. Success requires exit code zero and JSON stdout:

```json
{"ok":true,"status":"sent","messageId":"provider-message-id","deduplicated":false}
```

Other results are displayed as failed/unknown, not success. The executable must be trusted and configured by the device owner. Keep credentials and recipient IDs outside the public project. The UI test is clearly marked as a test, has a persistent ID, and will not send a second message after success or an uncertain outcome. It does not turn on external-operation alerts.

## Complete physical calibration

The local G100 preview is installed with `remote_verified=true`, `physical_verified=false`. Ordinary ADB access, an open reader, synthetic parser tests and absence of remote input in the kernel stream are not a positive physical-input test.

Before enabling alerts, verify real physical touches and every key node included in coverage while the console and Agent are idle; compare remote manual and leased Agent actions; exercise idle notifications, merging, cooldown and reader recovery. Record the actual time, input type, selected node and resulting summarized event. Only then may the owner/maintainer write `activity-validation.json` with the current aggregate node fingerprint, both verification flags true, and an evidence reference. The UI cannot silently promote unverified nodes to verified.

Repeat the physical comparison with the physical panel on and off. A dark panel may also stop touch scanning on a particular phone; an open input reader does not prove that the touchscreen continues reporting touches in that state. Do not advertise coverage of touches that the hardware does not report.

On 2026-10-17 the owner could not physically reach the G100. Two actual Agent taps and two actual manual-console taps were recorded under their respective sources, with zero device-input records. A single Feishu test was sent and read back; invoking the test again reused its result. **Physical input detection and real external-operation alerts remain pending.** The earlier maintenance automation remains paused.
