# Phone Harness

[中文](README.zh-CN.md) · [Preview releases](https://github.com/maxi-max-dev/phone-harness/releases) · [Report an issue](https://github.com/maxi-max-dev/phone-harness/issues/new/choose)

A local Android control console shared by humans and their AI assistants.

**The assistant you give the task to remains its executor.** Codex, Claude Code, Jarvis or another MCP client can use the same phone. This project supplies a screen, tools, task queue and ownership protocol. Model execution stays in the original assistant host; the optional OpenClaw adapter can resume that host's original conversation after human control is returned.

Version 0.7.0 is an **MIT-licensed open-source preview** of a local, single-phone prototype. The current implementation uses Unix file locks and is intended for macOS/Linux; Windows is not supported yet. Real-device acceptance is limited to the device and capabilities listed in `VALIDATION.md`.

![Phone Harness light console — synthetic demonstration](docs/console-demo.png)

*Illustrative UI preview. The phone screen and task data are synthetic; no real phone content is shown.*

## What it does

- Real H.264 scrcpy video in a macOS app window or browser, with pointer, navigation keys and explicit Unicode paste.
- Visible action feedback: large tap rings, swipe paths/arrows and short action labels. Human input is amber; assistant input is lavender. Released human gestures fade within 450 ms, assistant gestures within 900 ms; a new gesture retires the preceding one within 120 ms, without accumulating a click history. Session settings offer three sizes or hide the overlay. It is desktop-only and does not show typed text. A cue means input was dispatched, not that the intended UI result was verified.
- Human takeover invalidates the agent lease immediately. A call already sent to Android may finish; new calls stop. Late results cannot complete a paused task.
- Tasks retain their original agent, checkpoints and results. Reordering changes the waiting queue; **Prioritize** also pauses the current task.
- Physical panel off by default, with a live indicator and explicit on/off control. Local audio muted, known haptic settings disabled. Battery and battery temperature are read from the phone.
- Compact status icons open audio, charging, sample-time and device-activity details. Rear torch/camera/microphone/system screen-capture/call activity raises a visible banner. Stale or unsupported state is unknown, not idle. No camera or microphone content is collected by the monitor. Torch state uses SystemUI callback state and is unknown while unavailable. It does not establish camera flash firing, camera-controlled lighting or front-screen illumination; polling can miss brief use.
- Quiet mode verifies basic streams separately from voice-call and Bluetooth-call streams. It attempts idle call-channel muting through Android’s audio shell; a successful command alone never proves silence. Calls or route changes may reset state, and acoustic silence during real calls has not been established.
- Connection failure pauses tasks. Up to three bounded reconnect attempts restore the transport while a viewer is open, but do not replay input or resume work automatically.
- By default, closing the last viewer pauses the queue and ends the phone session after 12 seconds. The settings switch can keep the session available for an already-authorized persistent agent. The small local server remains available either way.
- MCP stdio bridge and a portable agent Skill. No model credentials, cloud relay, analytics or automatic feedback upload.

## Install

[中文快速开始](README.zh-CN.md). On macOS you can use an independent native WebKit window, with no browser tab or address bar. The browser remains an optional cross-platform viewer.

Requirements: Python 3.11+, Node.js/npm and Android platform-tools (`adb`) from their official projects. macOS desktop installation also needs Apple Command Line Tools. Linux uses a WebCodecs-capable Chromium browser. Windows is not supported yet.

```sh
git clone https://github.com/maxi-max-dev/phone-harness.git
cd phone-harness
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/phone-harness setup --install-dependencies
.venv/bin/phone-harness doctor
.venv/bin/phone-harness install-app       # macOS: creates ~/Applications/Phone Harness.app
# Alternatively, on macOS or Linux:
.venv/bin/phone-harness open              # opens the browser viewer
```

Connect/unlock the USB phone and authorize debugging before setup. Setup binds the only authorized USB phone; with several phones use `--serial`. It downloads the official scrcpy **5.0.1 server**, checks its pinned SHA-256, installs Mobile MCP **1.0.9** into private state (retaining npm's lockfile), and writes a private configuration with mode 0600. It refuses to overwrite an existing configuration. Host prerequisites are not silently installed or upgraded.

For offline/existing dependencies, use `setup --scrcpy-server /absolute/server --mobile-mcp /absolute/node_modules/@mobilenext/mobile-mcp/lib/index.js`. `--adb`, `--node` and `--operation-lock` support existing host tools and cooperative locks. `--state /private/path` selects an isolated installation and must precede the command. Existing configurations made from `config.example.json` remain supported.

Open **Phone Harness** from Applications and click **连接手机**. `doctor` checks host dependencies and USB authorization without navigating the phone; it does not prove real UI compatibility. A temporary independent installation was exercised on the tested Mac; that is not another person's device acceptance.

The server binds only loopback; remote desktop to the host is the intended remote viewing path. Do not expose this port to a LAN or public tunnel. Endpoint tokens are local process credentials, not multi-user authentication. Neither interface starts a phone session automatically.

On first connection the phone must be unlocked and USB debugging authorized by its owner. The console does not bypass a PIN or authentication screen. Starting the session may briefly illuminate the physical panel before the server turns it off.

## Connect an assistant

Configure a standard stdio MCP server in the assistant you already use. For a client with JSON MCP settings:

```json
{
  "mcpServers": {
    "phone_harness": {
      "command": "/absolute/path/to/.venv/bin/phone-harness",
      "args": ["mcp", "--agent", "claude-work", "--name", "Claude Code"]
    }
  }
}
```

For a client with TOML MCP settings:

```toml
[mcp_servers.phone_harness]
command = "/absolute/path/to/.venv/bin/phone-harness"
args = ["mcp", "--agent", "codex-work", "--name", "Codex"]
```

Another persistent MCP host can use the same command with its own stable `--agent` identity. For Jarvis/OpenClaw, use the per-conversation adapter below rather than giving every conversation the same MCP identity. Use a **different identity for each simultaneously active client**, even if both are Codex. Do not configure two live clients with the same identity: reconnecting that identity invalidates its earlier lease. Identity labels are coordination identifiers, not a security boundary against malicious programs on the same user account.

Install or give the assistant `skills/phone-harness/SKILL.md`. Its loop is:

1. `phone_status` registers this client and reads ownership.
2. `phone_submit` adds the authorized phone subtask.
3. After the user selects **交回助手**, `phone_wait` acquires its next task.
4. `phone_tools` returns the actual device tool schemas. Observe the current screen, save a checkpoint, act once, observe again.
5. `phone_finish` records a verified result or blocker and releases the phone.

If the user takes over, the old lease stops working. The assistant waits and reacquires; it must not open a different ADB path to bypass the pause. An offline head-of-queue owner blocks that task; the console never assigns it to another model. The user can prioritize a different task explicitly.

An assistant must stay running and call `phone_wait` to consume tasks. Adding a task in the UI alone does not start Codex or Claude Code. The included OpenClaw adapter owns that lifecycle for existing Jarvis tasks after control is released.

## Jarvis / OpenClaw

The included native OpenClaw adapter reuses the same broker protocol. Each conversation gets its own identity derived from host context, so one chat cannot claim another chat's phone tasks. The portable Skill is included in the plugin.

```sh
python3 integrations/openclaw/install.py --agent main --name Jarvis
openclaw config validate
```

The installer backs up the existing configuration/plugin, adds only the seven phone tools, and preserves model selection and unrelated permissions. It targets an existing agent. If OpenClaw does not hot-reload the plugin, restart its gateway when idle. Tested on OpenClaw 2026.7.1-2. Older hosts without the runtime APIs are not established compatible.

The adapter also continues an already-queued phone task in its **original conversation** after the user gives control back, even when that conversation's previous turn has ended. It uses OpenClaw's normal agent runtime, never a new model or different assistant. It checks queue metadata, not phone screens; it starts nothing while the human owns the device, while an agent turn/lease is active, after a conversation reset, or without an existing task. Continuations have no host message tool or external delivery, and are bounded to three wake attempts per task until the user takes control again. An explicit new handoff resets that allowance. It does not create a cron or maintenance automation. The setting `plugins.entries.phone-harness.config.resumeOnRelease` disables/enables this behavior.

When OpenClaw is stopped, the Mac sleeps, or the model is unavailable, the queue cannot promise execution. Results remain in the console. On a concrete failure, inspect the local `openclaw-resume.json` and continue the same conversation; do not duplicate the task.

## State and recovery

Private state defaults to `~/.local/share/phone-harness`; `--state /other/path` can isolate an installation. `queue.json` stores task text, checkpoints, results and recent events. A restart preserves them and starts paused. A two-minute lease expires when the assistant stops making calls. Tasks have a 200-tool-call budget; a blocked task can be requeued after review.

`operation_lock` coordinates with an existing phone gateway. Every cooperating tool and manual mirror must use the same lock. The console holds it for the entire live session, including manual control. Raw ADB programs outside this protocol are not sandboxed by this project.

`quiet-original-*.json` stores the original settings once; `quiet-verification.json` records software readback. Quiet settings remain in effect after exit to avoid unexpected sound. Restore them only when the owner requests it. The one-click quiet control re-applies the settings. The status bar reports DND and the system haptic setting; session startup checks five audio streams. Third-party keyboard vibration, emergency/OEM audio, acoustic silence, cold boot and long unattended use require separate acceptance. System settings are not an acoustic measurement.

Phone observation guards expire after 120 seconds and after every input. This pinned Mobile MCP release has unreliable element refs on the tested ROM, so refs are rejected and fresh coordinates are required. The broker rejects another serial and separates text paste from submission. The clipboard is used for explicit paste; avoid this path for credentials. Phone contents are untrusted source data, not instructions.

## Development and feedback

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check src/phone_harness/web/app.js
node --check src/phone_harness/web/actions.js
node --test tests/actions.test.cjs
node --test integrations/openclaw/bridge.test.mjs
python3 -m pip wheel --no-deps . -w dist
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the no-device UI preview and contribution workflow, [SECURITY.md](SECURITY.md) for trust boundaries, and [THIRD_PARTY.md](THIRD_PARTY.md) for dependency licenses. The light workspace direction and editable design brief are in [docs/DESIGN.md](docs/DESIGN.md).

Report behavior through the included issue templates. Include your OS, Android version, browser, what you expected, actual behavior, and whether human takeover worked. Do not attach a serial, endpoint token, queue file, full phone screenshot or private task contents without reviewing it first. No feedback is uploaded by the application.

The UI borrows the compact top bar, large device stage and narrow side toolbar from [BlueStacks' documented layout](https://support.bluestacks.com/hc/en-us/articles/360055672212-How-to-use-the-Side-toolbar-in-BlueStacks-5). Gaming macros, emulation and multi-instance controls are intentionally outside this real-phone console. Transport follows [scrcpy 5.0.1's protocol](https://github.com/Genymobile/scrcpy/blob/v5.0.1/doc/develop.md); semantic tools come from [Mobile MCP](https://github.com/mobile-next/mobile-mcp). These independent projects are not affiliated with this prototype.

## Physical-screen control and compact view (0.3)

The right-hand lamp/button reports the **physical internal display**, separately from the video. Green means verified off; amber means on (including low-power visible display modes); grey means unknown. Click it to request explicit on/off, followed by device readback. Streaming continues with the panel off. On connection the default is off.

The panel monitor reads system metadata approximately every 1.5 seconds, independently of long assistant actions; the UI polls every second. Samples older than five seconds and disconnected sessions show unknown. This is a system readback, not a camera or optical measurement, and flashes shorter than the polling interval may be missed.

The phone stays centered in the whole window. The task drawer starts collapsed and never pushes the picture sideways; on narrow windows it overlays temporarily, with covered phone input disabled until you close it. Tools follow the picture’s right edge. The full phone picture fits without cropping; focus view gives it more height while keeping takeover visible. The rotate button requests native Android portrait/landscape while you own control. Some apps/lock screens enforce an orientation; the console reports that case instead of claiming a successful switch.
