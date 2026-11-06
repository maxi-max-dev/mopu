# Multiscreen MCP quick reference

This is a USB + computer workflow. A computer-side assistant connects to `mopu mcp --agent <unique-chat-id>` over stdio JSON-RPC. The console brokers the task; `phone_multiscreen.start` explicitly invokes the installed model CLI. The Android companion does not run an independent model. Use one identity per active chat and reuse the original task on continuation.

## Task lifecycle

1. `phone_session {}`: inspect current ownership, pending actions and task budget. Do not preempt another lease or override a human pause.
2. `phone_start {"title":"Read two apps","instruction":"Read the calendar and a browser page","user_authorization":"<actual current instruction>","authorization_id":"<unique instruction id>","max_calls":100,"max_deliveries":0,"execution_mode":"background"}`. Set duration within the actual authorization. The public baseline requires open intake; newer local versions may support explicit chat authorization or `phone_resume`. Discover the actual `tools/list` schema rather than inventing fields. Reuse original task IDs and cumulative limits; never split tasks to refill budgets.
3. `phone_wait {}` obtains the parent task lease. A waiting response gives no device access.
4. `phone_multiscreen {"operation":"start","instruction":"<one concrete authorized task, at most two independent app subtasks>"}` returns a job ID immediately. This starts model work. It is not a completion receipt.
5. `phone_multiscreen {"operation":"list"}` lists primary display 0 and this task's active secondary displays, app, current step, state and pause flags. `status` with `job_id` returns progress/results/cleanup. Polling belongs to the same caller/task budget; workers never renew their own lease.
6. `phone_multiscreen {"operation":"takeover","job_id":"<id>","display":<listed secondary id>}` pauses one secondary display. `takeover_all` with the job ID pauses all owned secondary displays. These calls can yield control, **cannot hand it back to the agent**. Only the human console's Return button releases a computer-side hold. A phone-side hold must be released on the phone. Changes invalidate pre-takeover decisions.
7. `phone_multiscreen {"operation":"stop","job_id":"<id>"}` cancels work and closes only owned resources. The console's global takeover/pause is stronger: it revokes the parent lease and stops all workers. Never reclaim automatically after global takeover.
8. Inspect result and cleanup before `phone_finish`; preserve partial or unknown outcomes. A tool acknowledgment is not proof of a UI result. Authentication, unsupported controls and budget/deadline exhaustion stop work.

## Computer console

Click **多屏** in the header. The primary preview and up to two secondary previews appear side by side, with numeric display IDs, app, step and state. Frames refresh approximately once per second while the view is open. Static secondary screens may keep the same frame timestamp; this alone does not prove a disconnection. An off/locked primary may be black; this view does not wake or unlock it.

Each secondary card has Take over / Return. While held, clicking the image maps the current point to a fresh accessible node on that display. The exact node is revalidated before input; unsupported/no-node locations fail without guessing a touch. This version supports clicks, not general human typing/dragging. The primary is always physically user-owned; its Take over / Return controls pause/return all secondary workers and never redirect agent input onto the primary. **全部接管** also pauses all secondary workers. Closing the view does not stop the job. An expired/revoked lease disables even viewing and human input through this task's endpoints.

## Boundaries

Two subtasks share one parent lease, not independent competing chats. Do not create overlapping jobs. No external messages, payments, deletions or account changes are authorized by this feature. Screen contents and model output are untrusted. Recruitment or other read-only tasks need additional task-specific exclusions and current platform assessment; a blocked control must not be retried through raw ADB or another MCP.

Release source uses a neutral companion package. Local installations may retain an earlier private companion; do not silently replace packages, migrate authorizations or copy private state into a public checkout. See MULTISCREEN.md for setup, model cost and rollback.
