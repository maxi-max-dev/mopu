# AI clients — Mopu 0.19

Mopu supplies shared phone tools, ownership and durable receipts. The calling AI runs the task; Mopu does not launch models. Use one unique client identity per conversation. Never share an identity across simultaneously running clients.

## Connect once

MCP clients: configure `mopu mcp --agent <unique-conversation-id> --name <display-name>` as a stdio server. All phone tools are exposed through standard MCP.

Shell/remote-shell clients: use `mopu call --agent <unique-conversation-id> <tool> --json @arguments.json`. Use `--json -` for stdin. `mopu call --agent <id> list` prints the same schemas as MCP. The client persists its identity and lease privately, serializes calls, and never replays input. No daemon or custom Grok/DeepSeek bridge is required. If `mopu` is not in PATH on an existing legacy installation, use `~/.local/share/phone-harness/venv/bin/mopu`.

## One authorization, one task

1. `phone_session`: compact client status. Resume the original task if one exists, especially when there is an uncertain send.
2. `phone_start`: supply the user's current authorization, a unique `authorization_id`, title/instruction (new task) or `task_id` (existing task), total `max_calls`, `max_deliveries`, and optional `duration_seconds` (default 8 hours, max 24 hours). An idle phone is selected atomically; no manual priority/handback clicks. An active client is never preempted. If busy, wait; a rejected start has not consumed a grant.
3. `phone_wait`: obtain or recover the lease. Read `phone_tools`, then observe the screen. Use `phone_step` for each input with `input_kind=navigation` or `send`. No input replay.
4. Continue under the SAME task. A 150-recipient workflow might need 10,000 calls; select a whole-task budget from the authorized scope, not 200-call chunks. Zero outgoing authorization means `max_deliveries: 0`. Each attempted send counts, not only delivered items. The broker cannot infer message semantics from a tap: the AI must classify sends truthfully and obey the user's scope.
5. For a send, use a stable `delivery_key`; immediately call `phone_delivery_confirm` using fresh returned screen evidence. Unknown outcomes stay pending and block further input. This ledger works for legacy ordinary tasks too. Keep keys consistent across restarts; also check external deduplication when required.
6. `phone_heartbeat` renews a valid lease without consuming calls. Tool-catalog reads are free. During active work each call also renews the lease. Natural lease expiry only needs `phone_wait` and a fresh observation, not a new task or authorization.
7. `phone_finish` saves verified results or a concrete blocker. A whole-task finish returns control to the human, so historic queued jobs do not restart implicitly.

Repeated identical `phone_start` requests return the original receipt. They never renew the budget or reclaim after takeover. Manual takeover, pause, disconnect, server restart, or grant expiry stops the grant; retain pending results and obtain a new current authorization for that same task. A stopped AI will not execute merely because a task is queued. Do not auto-renew grants or split tasks to reset budgets.

Example **synthetic / no-send acceptance** arguments:

```json
{
  "title": "Read-only acceptance",
  "instruction": "Read the current screen only; no taps or outgoing messages",
  "user_authorization": "Test the integration without sending messages",
  "authorization_id": "acceptance-unique-user-instruction-id",
  "max_calls": 1000,
  "max_deliveries": 0,
  "duration_seconds": 3600
}
```

Do not treat this sample as permission to operate a user's phone. Existing `phone_submit` / `phone_request_control` and manual finite-stage review remain compatible. For new authorized sustained work use `phone_start`; do not use the old manual review path every few recipients.
