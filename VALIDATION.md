# Validation scope — Mopu 0.14.0

## Mopu rename acceptance — 2026-10-19

- 146 Python tests and 18 JavaScript tests passed; a clean virtual environment installed the wheel and passed the Python suite.
- Both `mopu` and legacy `phone-harness` completed stdio MCP initialization as Mopu 0.14.0, returned the same nine-tool catalog and read the existing connected console.
- The installed macOS Mopu app showed the renamed title, version 0.14.0 and live USB connection. Physical panel remained off; quiet status was read back.
- All 36 pre-migration task records remained identical and config bytes were unchanged. An existing client successfully queued a new task after migration.
- All 23 runtime source files matched the installed package. The old app path points to Mopu; the previous bundle and source are backed up privately.
- Human ownership was retained. This acceptance checks the rename and connectivity, not a new cross-app task or physical touch-alert acceptance. OpenClaw adapter files were updated and config validated; the running gateway was not restarted.

## Earlier acceptance history

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
- Initial acceptance stopped at the keyguard: normal remote swipe, the visibly unlocked device-entry icon and launching Settings did not dismiss it. No password was entered, security setting changed or physical panel intentionally turned on. The owner subsequently unlocked through the console; the follow-up below resolves the app-switching blocker.
- After the owner confirmed unlock, the existing acceptance task resumed on the same USB G100. Fresh observations confirmed the launcher, Settings, then the launcher again. The device-sourced Settings name appeared in the native activity sheet; its measured dwell increased from 10.7 to 32.1 seconds, closed at 34.2 seconds on returning Home, and stayed unchanged while the new desktop visit grew from 6.4 to 23.6 seconds. The native sheet displayed the app name, start/end, approximately 34 seconds, one assistant navigation key and the switched-app state. This establishes real app-name/switch/dwell acceptance, not physical-user identification. Control returned to the human; the physical panel read Off throughout the acceptance samples.
- Physical-touch acceptance and real external-input alerts remain pending. App visits describe sampled foreground presence, not continuous attention or the identity of an operator. No new Feishu notification was sent during this follow-up.
- 0.8.1 is installed locally, with existing history, test receipt and the physical-validation gate preserved. Formal external-input alerts remain disabled and `g100` maintenance remains PAUSED. No new Feishu test or alert was sent in this update; public release remains v0.6.0.

## Version 0.8.2 local preview

- External-input notifications now wait for 30 seconds without new input, then combine the session's counts, observed foreground App names and approximate dwell in one reminder. Repeated visits to the same package are summed; the time window starts at the first input and ends 30 seconds after the last. Only confirmed foreground intervals are counted. Missing app readings are explicit; they are not guessed or treated as zero activity. Earlier/later app use is excluded. Unfinished sessions are not notified after restart.
- 89 Python tests and 17 JavaScript/adapter tests passed, plus JavaScript syntax and wheel/native builds. Coverage includes no early send during continuous actions, exact merge boundary, repeated App aggregation, interval clipping, missing/locked readings, recent-visit eviction, content exclusion, restart, cooldown and unknown delivery without replay.
- Installed 0.8.2 in the existing native app. All 19 installed runtime files matched source and wheel; native version and updated merge explanation were verified. Existing task states, recording preference, calibration gate and original Feishu test receipt survived the service reload. USB video resumed, physical panel read Off, quiet channels read silent and ownership remained human. No phone navigation was performed for this notification-only change.
- One clearly labeled synthetic-format test was sent to the existing personal Feishu route. The provider message API read back the same message containing Settings approximately 34 seconds and Clock approximately 18 seconds, as well as the synthetic-test and calibration-pending labels. These values are test data, not a new real physical-operation event. The previous real-device App-visit acceptance remains separate.
- Physical positive calibration and real external-input alert delivery remain untested and disabled. The earlier `g100` maintenance automation remains PAUSED. The public release remains v0.6.0; this change is installed locally.

## Not established

- Claude Code has not been configured or exercised in this acceptance. The common stdio MCP adapter and the actual Jarvis/OpenClaw adapter have been exercised.
- Physical USB unplug/replug, cold boot, multi-day unattended operation, Windows, Linux and other Android models are not hardware-accepted.
- Silent settings are software readbacks, not acoustic measurements; third-party keyboard/app vibration and OEM/emergency audio are not comprehensively tested.
- Codex/Claude Code require their original host conversation to keep running or be resumed by the user. The optional OpenClaw continuation runs within the original host. The product does not sandbox unrelated raw ADB programs and does not expose a remote Internet endpoint.
- Source is published as a GitHub preview at https://github.com/maxi-max-dev/mopu. No package registry release, automatic feedback service or user adoption is claimed.

Evidence containing phone UI and local paths is stored privately in the testing host's state directory and excluded from this distributable.

## Version 0.9 local acceptance — 2026-10-18

- Added broker-linked acceptance receipts, explicit waiting reasons and a backend-confirmed capability catalog. Legacy result-only finishes remain unverified; historical tasks are not rewritten. A receipt means the original assistant judged new observations, not independent semantic verification.
- 107 Python tests passed, including forged/stale/cross-task/cross-lease references, input and uncertain-call invalidation, empty/error observations, text-only finish, persisted receipts, retry history, declared-wait suppression, exact next-action preservation and malformed call rejection. 18 JavaScript tests passed (11 action feedback, 7 OpenClaw adapter); JS syntax checks passed.
- Synthetic browser UI displayed capability and receipt sheets. Installed native app showed version 0.9.0 and decoded the actual USB stream; phone_tools confirmed all 14 permitted tools. This confirms backend availability, not every tool's end-to-end behavior.
- Real task d392f28880a2 attempted Settings/Battery acceptance under an exclusive lease. Ordinary upward swipe, unlocked-icon tap, Settings launch and HOME returned acknowledgements, but fresh screen trees still showed SystemUI's swipe-only lock screen. No credential prompt was observed and no credential was entered. Therefore the task was stored as blocked with a failed acceptance criterion, broker observation/time and unresolved item. Settings/Battery navigation is **not accepted in this run**. Logical wakefulness was Awake, physical panel Off and quiet telemetry true. The precise input failure remains unresolved; the UI being readable is not proof input worked.
- Human ownership was restored. Previous task history and local backups were preserved. No public release/push, no physical-input calibration claim, and no live Jarvis schema-reload claim.


## Version 0.9.1 — swipe-only unlock and completed acceptance

- Assistant swipes now use the same scrcpy touch packet path as the console, within the existing exclusive lease. Device-to-video coordinates are checked/scaled, each motion checks ownership, interrupted pointers receive UP cleanup, and failures never fall back or replay. Other input tools retain their existing backend.
- 112 Python checks passed, adding wire-coordinate, mid-gesture takeover, stale generation, invalid geometry and failure/no-replay tests. Existing 18 JavaScript checks passed in 0.9.0; JavaScript was not changed here.
- Real task d392f28880a2 was retried, preserving the prior failed receipt. A swipe beginning on the bottom unlocked-icon region still did not dismiss the lock screen even over scrcpy. Moving the start to the observed middle blank region (300,1600 → 300,500 at 1080×2400) succeeded. Thus the prior user-unlock blocker was premature; transport difference alone is not an established root cause, and the old ADB path at the corrected start was not isolated/tested.
- The original assistant then scrolled Settings, clicked Battery via the existing backend and read the actual Battery page: 79%, connected but not charging. Two fresh broker-linked checks completed the original task with assistant_verified. No settings were changed. Native UI showed both passed checks and one preserved previous attempt. Human ownership restored; panel Off and quiet telemetry true.

## 0.10.0：实机多 App 任务与单步读回（2026-10-18）

新增 `phone_step`：验证当前屏幕观察与租约、保存检查点、执行一个动作并返回新文字或截图。`expected_text` 只是文字匹配，不代表任务完成；读回失败不自动重放。文字输入改用现有控制台 scrcpy 剪贴板粘贴通道，输入与提交分离。

实机完成：计算器128×3+76=460；Moto笔记保存计算结果并重开核对；Chrome从example.com进入IANA说明页并阅读。高德停在首次协议，路线查询未完成。升级后中文标题直接写入，退出重开仍保存。121项Python、18项JavaScript检查通过。自定义编辑器/WebView仍需截图；队列不启动模型；OpenClaw适配文件已更新但网关未重启验证。

## 0.11.0：跨 App 阶段验收（2026-10-18）

提交时可声明 `required_milestones`；`phone_milestone` 在切换 App 前封存新鲜的阶段读回。阶段 key 不可覆盖，历史观察不会冒充当前状态；最终完成仍必须有新鲜读回，缺必需阶段则待核验。控制台详情展示阶段；中断续接保留，重试保留旧尝试并重置本次阶段。`phone_step` 可用 `read_attempts=1..3` 等待预期文字，仅重复读取，不重放输入。

真机完成：旧预算笔记→计算器→原笔记修订529元；Chrome官方说明→中文摘要笔记→重开；设置实时256GB/39GB→计算器217→中断续接→存储笔记重开。后两条使用0.11阶段约束。130项Python、18项JS通过；本机安装运行。OpenClaw文件更新但网关未重启，不宣称活跃Jarvis加载。仅3个有界任务样本，不是所有App稳定性或成功率证明。

## 0.12.0：日常购物重复验收（2026-10-18）

在既有0.11实现上加入精确目标点击：输入前重新读取目标，缺失/歧义/禁用/无有效坐标则不派发点击；严格解析后端元数据，不把网页文字中的伪坐标或disabled字样当元数据。9项新增Python用例覆盖重新定位、消失不点击、歧义/禁用、坐标冲突、接管、可见文字伪元数据；合计139项Python通过，18项JS通过。

- 购物比价→日历：d030aac06c6a / 619f02b79860 / 8d833dcd2d4d。手机Chrome实读JB Hi-Fi型号MWVT3X/A与Officeworks代码APMWVT3XA，Apple20W两店均A$29；运费、门店库存未知。唯一PH购物比较1018本地日程重开后内容、两条来源链接、不提醒、不重复正确。第二/第三轮复用原日程，目标日期仍1条。
- 官方说明书→超级文件：2629bbc478c8 / 709375ffb3cc / 8170fde78044。Apple官方20W说明书56页，下载后由超级文件独立打开并截图验证实际正文。三轮仅1份20W-usb-c-power-adapter-ug.pdf（文件管理器1.3MB），后两轮复用，无编号副本；第三轮从桌面开始并经文档/PDF分类定位。
- 实际异常：Chrome下载完成toast的打开入口会消失，改用持久文件列表；超级文件首次推广遮盖文档入口，fresh target返回target_missing/action_dispatched=false，关闭推广后继续；Motorola日历切换全天会重置提醒且禁用提醒编辑，改为普通时段后设置不提醒并重开验证。这些观察写入操作skill。两应用协议已有用户当次明确许可；日历短信权限拒绝；未购买、上传或发送。
- 这6个是同日同设备的有限样本，有原助手持续观察/决策，不是无人值守稳定率。零售商通过Chrome访问，未测试淘宝/京东登录、购物车、优惠券、付款、复杂规格组合；价格仅当次显示，非到手价。没有后台模型启动、长期运行、断网恢复或活跃Jarvis重新加载证明。OpenClaw适配文件同步，网关未重启。
- 最终严格解析包安装后的目标点击兼容性另作只读烟测，不把它计为第7个完整购物任务。包含手机内容的原始记录留在本机私有state，发行源码仅含代码/测试/说明，不含用户截图或队列。

## 0.13.0 shopping acceptance (2026-10-18)

`phone_step` adds bounded `settle_ms=400..5000` before the first readback (default400) for observed lazy-loaded screens. It never repeats input; takeover is rechecked before reading. Waiting is not a readiness assertion. Shopping skill guidance now separates SKU, promotion eligibility/stacking, display currency and unknown delivery fees.

Physical G100: three repeated Xiaohongshu F63 white/quantity1 checks sealed SKU, coupon and shipping stages; all agreed on CNY399−71=328 (approximately AUD71.33), black sold out. Cross-border freight remains unknown, so all three final receipts are unverified. No coupon claim, cart addition, checkout, order or payment. Twelve 3000ms screenshot readbacks (two SKU, ten detail swipes) were inspected; cache/network were uncontrolled, not a general reliability rate. 142 Python and18 JavaScript tests passed;22 installed runtime files match source. Local0.13 only; public release unchanged; OpenClaw files copied without gateway restart.
