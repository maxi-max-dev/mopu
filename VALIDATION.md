# Validation scope — 0.7.0

Local acceptance on 2026-10-17 (Australia/Brisbane). This is a prototype build, not a published service or evidence of adoption.

## Verified

- macOS ARM64, USB Motorola phone running Android 15; local H.264 720 × 1600 stream decoded in the browser. Dynamic content reached approximately 60 delivered frames/second; this is not a measured end-to-end latency guarantee.
- Physical SurfaceFlinger internal display `Off`, logical wakefulness `Awake`, virtual scrcpy display `On`. Battery percentage and battery temperature read back separately.
- Startup readback of SYSTEM, RING, MUSIC, ALARM and NOTIFICATION streams; known system haptic/keypress settings disabled. No audio stream forwarded to the Mac.
- Existing manual mirror lock refused; after closing that window, console connected successfully.
- Web manual click into Settings search, Chinese clipboard paste, visible `显示` result; assistant then read the same text through Mobile MCP and cleared only the test text.
- Standard stdio MCP initialize, seven-tool catalog, registration, original-agent task acquisition, fresh observation, Chinese input/readback, clear/readback and verified task completion.
- Human takeover invalidated an old real task lease; a subsequent input attempt was rejected before device dispatch. Returning control required fresh observation and preserved the checkpoint.
- Queue form submission, move-up and explicit priority change; priority invalidated the previous task lease and retained progress.
- 19 Python tests cover ownership, queue persistence, timeout handling without replay, in-flight handoff, identity separation, wrong-device/ref rejection, stale geometry, local HTTP origin/token checks and first-use setup selection/privacy.

- App launcher started the installed package and opened its local browser console; a server restart retained task order, checkpoints and results and did not auto-resume.
- Deliberately terminating only this console's video transport recovered its connection on the first bounded retry in about 20 seconds. Tasks stayed paused and the physical panel remained Off; this is software transport recovery, not a physical cable test.

- Closing the last viewer with the default preference ended the session and paused the queue; independent readback confirmed physical panel Off, DND still enabled and logical Dozing.
- The background-continuation preference can be saved from the UI; default was restored to pause-on-close. Multi-day unattended execution remains unverified.

## Version 0.2 additions

- A compiled Cocoa/WKWebView application displayed the same real phone video on macOS 15.7.8 without a browser tab. Human takeover through its native window was exercised.
- The existing OpenClaw main agent (Jarvis), using its unchanged MiniMax-M3 model, registered a per-conversation identity and completed real Settings tasks through the adapter. Read storage capacity, use and remaining space; calculated remaining capacity was distinguished from direct UI readback.
- Two Jarvis tasks were queued. Human takeover during the first rejected its next swipe before dispatch. The tester manually opened Android Recents. After release, Jarvis observed Recents and resumed the first task, then completed the second; the rejected swipe did not cause that navigation.
- A follow-up checked actual battery-setting pages because the original report inferred switch state from menu descriptions. Standard and extreme battery saver were off; overcharge protection was on. Auto display timeout was one minute. Physical panel-off, logical wakefulness and Android timeout are distinct; timeout alone does not establish whether this mirroring session sleeps.
- An ended Jarvis turn was resumed automatically in its original conversation by the desktop **交回助手** button. The new host turn used the same MiniMax-M3 model, acquired the already-queued task, observed the current phone UI and read Android version 15, then marked the task done. No additional manual "continue" prompt was sent after release. The first candidate incorrectly relied on a restricted raw-conversation hook; the accepted adapter uses the public host activity API and session work admission, without enabling that hook permission.
- Six adapter tests cover identity separation, non-loopback rejection, no failed-input replay, busy/ownership guards, original-session work admission and renewal of the bounded allowance after manual control.
- A separate clean virtual environment on the same Mac installed the source package, downloaded its own pinned dependencies, bound the authorized USB phone and passed `doctor`. Its independent Mobile MCP handshake listed 33 tools. No phone navigation was performed by this installation. This verifies the install path on this host, not another person's machine.

## Version 0.3 additions

- The installed native macOS app was exercised against the same USB G100. Clicking the panel indicator produced physical internal display `On`, then `Off`, with the indicator matching each readback. Video remained connected and interactive with the panel off. No external camera or optical brightness measurement was used.
- The panel monitor is independent of the assistant action lock. Ten new tests cover physical-vs-virtual parsing, multiple panels, doze visibility, unknown data, stale/disconnected readings, explicit on/off readback without replay, failed-read invalidation, monitoring during busy operations and rotation ownership. All 29 Python tests pass.
- Settings rotated from 720 × 1600 to 1600 × 720, the decoded picture resized to the available width, and a click on the landscape Settings search field opened its keyboard. It returned to 720 × 1600 portrait. Physical panel stayed Off and quiet settings remained enabled.
- Task/history drawer starts collapsed and can be opened on demand. The idle task footer is hidden, ownership controls remain visible, and portrait video fills the available vertical space with 4 px inset.
- Panel status comes from approximately 1.5-second system polling and one-second UI synchronization, not instantaneous optical observation. A flash shorter than the polling interval may not be detected. Unknown or stale state is never reported as verified off.

## Version 0.4 additions

- Installed native macOS app: compact status icons and clickable audio, charging and last-read details exercised against the USB Android 15 device. Existing picture width and 23 px footer retained; device-activity strip appears only while active.
- Reported power supply AC, 79%, battery 25–26 °C, not charging, OEM 80% charging protection active. USB data connection is not treated as proof of battery charging.
- Diagnosed the user's system-phone sound report: voice call channel was unmuted at 6/8, even though several basic streams were silent. DND had also drifted off. This identifies possible output paths, not the exact audible sound heard by the observer.
- MediaSession volume-set acknowledgement did **not** change the call volume. Android `cmd audio set-volume` and `adj-mute` did: VOICE_CALL and BLUETOOTH_SCO read back `Muted: true`, volume 0 after the new quiet flow. DTMF, enforced/system, media, ring, notification and alarm streams also read silent; available keypad, touch, ring-vibration and system-keyboard feedback settings read 0. Originals retained in private backups.
- Opened the existing system camera for preview only under a queued Codex task. Current CameraService clients changed to the camera package; the native console displayed the camera-use banner. Back exited the camera, current clients became empty, and the banner cleared. Physical internal panel stayed Off. No photo or video captured.
- Microphone and MediaProjection idle state read successfully on the device. Active microphone recording, active system screen capture, external headsets and a real outgoing call were **not** exercised. No ambient audio recorded or external call placed. Call silence during dialing/connection, route changes or OEM sounds remains unproven.
- 41 Python tests cover the existing 29 cases plus live-vs-history activity parsing, mute/call separation, charging protection, unknown/stale/failed reads, old-session rejection, monitoring while agent actions run, audio-shell readback, playback-capture-vs-microphone distinction and projection formats. JavaScript syntax checked. The monitor samples metadata only and does not store raw audio/camera dumps in normal operation.

## Version 0.4.1 additions

- The same USB G100 exposes the current SystemUI `FlashlightControllerImpl` state: camera 0, torch available, flashlight disabled. The installed native app displayed **手电筒：已关闭 · 系统读回** with a successful read timestamp. Physical panel remained Off; existing queued work was preserved and control returned to the human.
- Rear torch state joins the existing compact device-activity icon and conditional activity banner. Unavailable/cached, missing, conflicting, failed or stale data does not establish off. The detail view explicitly separates camera flash firing from the torch reading.
- 44 Python tests pass (three additional torch parser cases), JavaScript syntax passes and all 14 installed runtime files match source. This is real-device off-state and native-detail acceptance; the light was **not** deliberately turned on, so the physical on-state/banner transition remains untested. Short flashes, camera-controlled illumination and front-screen fill are outside this monitor's coverage.
- Sources: [SystemUI flashlight callback/dump implementation](https://android.googlesource.com/platform/frameworks/base/+/587ddafcc5f0cfd15fa370fdea7b08e3ab649b26/packages/SystemUI/src/com/android/systemui/statusbar/policy/FlashlightControllerImpl.java), [Android TorchCallback](https://developer.android.com/reference/android/hardware/camera2/CameraManager.TorchCallback).

## Version 0.5 additions

- Real USB phone, installed native macOS window: a manual blank-area click displayed an amber ring and generic click label. A dedicated Codex task issued a blank-area tap and a 300-device-pixel upward swipe; consecutive native screenshots captured the lavender tap ring, correct vertical path/arrow, and action labels. Actual stream events carried normalized tap coordinates (0.5, 0.541667) and swipe endpoints (0.5, 0.625) to (0.5, 0.5) against a 720 × 1600 stream; input dimensions were 1080 × 2400. No chat was opened, message sent or private text entered.
- Native settings changed size to larger and back to prominent; visibility was switched off and back on. Default remains enabled, 64 CSS-pixel diameter. Physical panel read Off and control was handed back to the human; the existing unrelated task remains paused with its checkpoint preserved.
- 53 Python tests and seven JavaScript action-state tests passed. They cover normalized/scaled/rotated geometry, backend-matching swipe paths, missing geometry, private-payload omission, refused input, takeover before backend dispatch, uncertain outcomes without replay, bounded/fading traces, hidden overlays and stale events. JavaScript syntax also passed. Automatic tests do not establish every gesture on hardware.
- Feedback is ephemeral and desktop-only. Read-only calls have no input cue; text/URL input has a generic label without its contents. Agent input is marked sent, returned awaiting visual verification, or uncertain. Old completion events cannot resurrect a cleared gesture.
- Real long-press/double-tap/text/navigation cues and landscape action overlays were not exercised in this update. Only their covered software behavior is established. No new acoustic, flash-on, multi-day unattended or other-device acceptance is claimed.

## Version 0.5.1 additions

- Live-use feedback supersedes the 0.5.0 duration: released manual gestures now clear within 450 ms, agent gestures within 900 ms. Each new gesture retires the preceding one within 120 ms, fading from its current opacity; older gestures are removed. Manual labels clear within 650 ms and agent labels within 1200 ms. Completion callbacks do not extend either lifetime or replace the latest action.
- The existing colors and size choices remain; fill alpha is reduced from 0x25 to 0x12. Held manual gestures remain visible until release (with the existing bounded stale-touch timeout).
- All 11 JavaScript action-state tests passed, including rapid input, fade continuity, held-pointer retirement, delayed completion and the prior coordinate/visibility checks. This patch changes desktop presentation only; previous real-device input acceptance is retained rather than replaying phone tasks.

## Version 0.6 additions

- Graphite presentation refresh: original thin-line SVG icons, restrained blue handoff action, rounded tool dock, segmented queue/history tabs and native-style settings switches. No new frontend dependency, phone control command or queue protocol. Reduced motion and keyboard focus are supported.
- Browser fixture at 1280 × 828 and the native minimum content size of 850 × 618: inspected portrait/landscape fit, queue collapse, focus view, handoff controls, settings and charging detail. Portrait height remains 723 px and 513 px respectively with the current-task footer visible (4 px top/bottom inset); no horizontal overflow. The narrower layout keeps control ownership visible. This is a synthetic UI exercise, not real phone input acceptance.
- Installed 0.6.0 into the existing local macOS app and reloaded its live viewer. Native UI reported 0.6.0 and decoded the real 720 × 1600 stream. Settings opened/closed successfully. Physical panel remained Off, ownership stayed human and existing task statuses were unchanged. All 16 installed runtime files and served frontend files match source.
- 53 Python tests, 11 action-overlay JavaScript tests and six OpenClaw adapter tests passed; syntax checks and wheel build passed. CI configuration was prepared for macOS/Linux, separately from these local results.
- Public preview uses an original synthetic phone illustration and synthetic tasks, visibly labeled DEMO. No device serial, active local credential, private configuration, queue dump or real-phone screenshot is included in the shareable source.

## Version 0.6.1 additions

- Local review rejected the Graphite palette. Replaced it with light surfaces, charcoal text and primary actions, soft neutral task/sidebar separation, an integrated right tool column, restrained selected rows and simpler headings. Native macOS title bar and loading page use light appearance as well. No new frontend dependency or control protocol.
- Synthetic browser checks at 1280 × 828 and 850 × 618 covered portrait and landscape fit, takeover/release button states, settings, battery detail and focus mode. Portrait height remains 723/513 px with the task footer, and 757 px in focus mode at the larger size. No horizontal overflow or browser console warnings/errors observed. Synthetic interactions are not phone task acceptance.
- Installed 0.6.1 and reopened the native app while keeping a second viewer connected. Real 720 × 1600 video continued; the native light title bar, new UI version and settings open/close were visually verified. Physical panel remained Off, ownership stayed human and task IDs/statuses were unchanged. No phone input was sent. All 16 installed runtime files and served JavaScript/CSS matched source.
- 53 Python, 11 action-feedback JavaScript and six adapter tests passed. JavaScript syntax, wheel build and native app compilation passed. The existing aiohttp test fixture emits a non-failing AppKey warning.
- This version is installed locally for visual review. The published GitHub release remains v0.6.0; no new release or external-use claim is made here.

## Version 0.7 additions

- Reworked the composition around the full window centerline: independent video stage, optional left task drawer, right tools attached 16 px from the video edge, one ownership header and compact status footer. Removed the redundant current-task footer; task progress and detail remain in the queue. No backend or ownership protocol changes.
- Synthetic browser checks at 1280 × 828, 850 × 618, 850 × 950 and 390 × 844 covered portrait, landscape, open/closed drawers and focus. At 1280 × 828, the portrait center is exactly x=640 with the drawer open or closed, height 750 px (previously 723); focus reaches 776 px while retaining takeover. Landscape is centered at x=640 with width 1104 px and no toolbar overflow. No horizontal overflow observed.
- Narrow-window drawers use a scrim and inert video/tools. The browser confirmed both inert attributes, hidden controls in the accessibility tree, and Escape restoration. Synthetic task move-up/down, takeover/release, settings and focus controls worked. Device status retains its semantic color on hover. No browser warning/error observed.
- Installed 0.7.0 into the existing native macOS app. Real USB video decoded, the phone was visually centered, and opening/closing the drawer correctly hid/restored covered phone controls in the native accessibility tree. Task IDs/statuses stayed unchanged, physical panel read Off and ownership remained human. No phone input or task execution was performed during this visual update.
- 53 Python, 11 action-overlay JavaScript and six OpenClaw adapter tests passed, as did JavaScript syntax, package build and native app compilation. All 16 installed runtime files and served frontend files matched source. Current release remains v0.6.0; 0.7.0 is local for review.

## Version 0.8 local preview

- Added a compact activity icon and detail sheet to the existing native app. Local summaries record input channel, time, gesture type and count, without input text, coordinates, screenshots or foreground-app content. Continuous actions merge into one record; calibrated external alerts wait 10 seconds initially, send once per continuous session and have a 5-minute cooldown between sessions.
- The real USB G100 permits read-only `getevent` access. Four candidate nodes (direct multitouch, power and two volume-key nodes) remained open, but the OEM denied readable input topology. These nodes are explicitly unverified candidates, not proof of physical provenance.
- Two actual leased Agent taps and two actual manual-console taps were exercised and observed on the phone. Each channel produced one record with two taps; the candidate kernel readers produced zero device records. This establishes the tested remote-input negative comparison, not physical touch detection. The owner could not reach the phone, so **physical positive acceptance and official external-operation alerts remain pending and disabled**.
- One clearly labeled Feishu test was sent through the owner's existing personal notification route. The provider's message API read back that message. Repeating the test and restarting the console retained the same receipt without another send. This does not claim the owner read the message or that a real physical-input alert fired.
- Native UI recording off/on was exercised: off closed all four readers, on restored all four and showed the pending-calibration status. A console restart recovered the connection/listeners and preserved records and receipt. This is software lifecycle recovery, not physical USB unplug/replug acceptance. The activity sheet was closed afterward; ownership remained human, physical panel read Off, and another chat's queued task was preserved.
- 70 Python tests, 11 action-feedback JavaScript tests and six OpenClaw adapter tests passed, plus JavaScript syntax and wheel/native builds. All 18 installed runtime files matched source and the final 0.8.0 wheel. The earlier `g100` maintenance automation remains PAUSED. This preview is installed locally; the public release remains v0.6.0.
- Actual touchscreen/power/volume input, panel-off touch reporting, real physical-input alert merging/cooldown and multi-day monitoring still need a person at the phone. Synthetic parser and notification tests are separate from those device acceptance steps.

## Version 0.8.1 local preview

- Added an App visits tab inside the existing activity sheet: actual application names from Mobile MCP metadata when available, package fallback, observed start/end, approximate foreground dwell and input categories by channel. The full name inventory remains in memory; only visited-app metadata is persisted. No page content, UI tree, screenshot, text, URL or window title is recorded by the monitor.
- 83 Python tests and the existing 17 JavaScript/adapter tests passed. New coverage includes focused-package/lock parsing, app-name metadata, switch intervals, source counts, unknown/locked/disconnected stops, stale samples, host-sleep gaps, clock changes, restart, private archive retention and content exclusion. Input-alert merging is unchanged by app transitions. Synthetic browser UI verified names, durations, source counts, two tabs and the compact recording switch; this is not phone task acceptance.
- On the USB G100, the filtered general window dump exposes current focus; its narrower `windows` dump did not suffice. The actual keyguard state was detected as locked and no underlying app visit was recorded. The installed native window correctly displayed “手机已锁屏 · 已停止 App 计时”. Mobile MCP returned actual installed-app display names.
- Normal remote swipe, the visibly unlocked device-entry icon and launching Settings did not dismiss the keyguard. Observations stayed on that screen. No password was entered, security setting changed or physical panel intentionally turned on. The owner was asked to unlock through the console when convenient. **Real app switching/dwell acceptance remains pending**, alongside the previously pending physical-touch acceptance; neither is claimed from the software checks or synthetic UI.
- 0.8.1 is installed locally, with existing history, test receipt and the physical-validation gate preserved. Formal external-input alerts remain disabled and `g100` maintenance remains PAUSED. No new Feishu test or alert was sent in this update; public release remains v0.6.0.

## Not established

- Claude Code has not been configured or exercised in this acceptance. The common stdio MCP adapter and the actual Jarvis/OpenClaw adapter have been exercised.
- Physical USB unplug/replug, cold boot, multi-day unattended operation, Windows, Linux and other Android models are not hardware-accepted.
- Silent settings are software readbacks, not acoustic measurements; third-party keyboard/app vibration and OEM/emergency audio are not comprehensively tested.
- Codex/Claude Code require their original host conversation to keep running or be resumed by the user. The optional OpenClaw continuation runs within the original host. The product does not sandbox unrelated raw ADB programs and does not expose a remote Internet endpoint.
- Source is published as a GitHub preview at https://github.com/maxi-max-dev/phone-harness. No package registry release, automatic feedback service or user adoption is claimed.

Evidence containing phone UI and local paths is stored privately in the testing host's state directory and excluded from this distributable.
