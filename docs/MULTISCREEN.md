# Experimental multiscreen tasks

This opt-in backend runs up to two independent app tasks on secondary displays.
The primary display remains outside the worker's input scope. The existing
broker still owns the parent task, lease, call budget, and human takeover.
Independent chats do not acquire concurrent leases by creating displays.

The executor discovers installed launcher activities, splits a request, and
repeatedly observes accessibility nodes and a screenshot before proposing one
action. It supports node clicks, text entry, scrolling, and search submission.
The bridge rechecks a unique target fingerprint immediately before dispatch.
A completed result needs current node evidence or a separate screenshot-based
model check; model verification is not independent human certification.

## Prerequisites and enabling

- An authorized USB Android device and a computer running the existing Mopu
  service, `adb`, scrcpy server 5.0.1, `ffmpeg`, and an authenticated Codex CLI
  supporting `exec`, structured output, image input, and ephemeral sessions.
- Android SDK platform/build tools and a JDK to build the companion app. Its
  source manifest declares the minimum API; compatibility beyond the tested
  environment is not established.
- The configured Mobile MCP installation must include its MobileCLI daemon
  command. The background backend gracefully stops that daemon to release its
  exclusive accessibility automation connection. It does not force-stop apps.

Build the companion from `android/multiscreen`:

```sh
export ANDROID_HOME=/path/to/android-sdk
export ANDROID_BUILD_TOOLS=35.0.1
./android/multiscreen/build.sh
```

Sign the resulting unsigned APK with your own Android signing key, stored
outside this repository, then install it on the explicitly selected device.
Never commit generated APKs, signing files or runtime state. The neutral app
identity is `dev.mopu.multiscreen`; it is a separate application from privately
named development builds and does not migrate their data or authorizations.

Enable the companion's accessibility service and its progress notifications on
the device. These are device-owner steps, not permissions silently granted by
Mopu. Confirm the bridge reports connected before running app tasks.

Install the Python package using the normal project instructions. Each explicit
invocation creates one bounded authorized task:

```sh
mopu-multiscreen 'Open the browser and read the first three section headings on a public documentation page'
```

For an existing assistant integration: `phone_start(execution_mode="background")`,
then `phone_wait`, then `phone_multiscreen(operation="start", instruction=...)`.
Inspect progress with `operation="status"`; stop with `operation="stop"`.
Status polling renews only the caller's existing lease. No worker grants itself
control. The ordinary task queue does not launch a model; the explicit
multiscreen operation does.

The companion lists each display, app, step and status. It offers individual
pause/takeover and an all-display control. Closing the desktop view does not
pause a background task. Whole-task takeover revokes the lease; no input is
replayed after reconnect or expiry. The current manual preview endpoint is
limited to taps and may be ineffective while the primary display is locked.

## Safety and limitations

- No sending, publishing, payments, deletion, or account/system-setting changes.
  Explicit local drafts are permitted. Model risk classification and target
  filters are safeguards, not a proof of arbitrary-app safety.
- No root, firmware changes, global display changes, or primary-screen input.
  A normal stream-to-background transition may restore the panel's previous
  on state after closing the old primary transport.
- Two independent app tasks only; cross-app dependencies are not orchestrated.
  A blocked screen retains its error while the other can finish. Mixed results
  are `partial`, never complete success.
- Each screen is bounded to 24 decisions; repeated identical actions stop.
  Pending-action checkpoints preserve uncertainty, including whether readback
  happened. A tool acknowledgement alone is not a successful user outcome.
- Login, initial consent screens, missing accessibility controls and some OEM
  behavior can block a task. Screenshots help reading but do not provide a
  reliable locked-screen coordinate-input fallback.
- Every step may invoke a model and transfer a screenshot plus visible app text
  to the configured model provider. Use only authorized task content. Current
  CLI startup/context overhead makes this substantially slower and more costly
  than a deterministic script; no fixed price or latency is promised.

## Scoped validation

On one Android 14 test device, a calendar read and browser documentation lookup
completed on separate displays; local text was saved and read back after
reopening. An inaccessible title control remained a partial result. Prior
integration testing exercised a prolonged locked-screen run and transport
termination, but these are not guarantees for every release build or app.

The neutral package and portable build are source-release adaptations. Software
tests and an unsigned build do not prove fresh installation/permissions on a
physical device. Simultaneous primary-screen human use, incoming calls and
physical USB unplug/replug remain separate acceptance items. Private screenshots,
model logs, note contents, device identifiers, and task receipts are not shipped.

## Disabling and rollback

Stop the current job, wait for owned displays and transport handles to close,
and verify no active lease remains. With the device idle, explicitly select
primary-screen streaming in the console if needed. Do not kill all ADB processes
or remove unrelated forwarding rules.

Stop the service before reverting this feature's source commits, then restart
using the existing state directory. Keep task history, cumulative counters and
uncertain external-action receipts; never restore an older queue snapshot.
The companion's accessibility service may be disabled by the device owner.
Retain app data and signing keys when rolling back; reinstalling a differently
signed app is not a data-preserving rollback.
