# Whole-task authorization (0.19.1)

For new authorized work use `phone_start` and the [AI client quickstart](AI_CLIENTS.md). A grant covers the whole task with 2–100,000 calls, 0–1,000 attempted deliveries, and an explicit duration (default 8 hours, maximum 24 hours). Zero deliveries forbids sends. The client supplies the user's authorization statement: this is trusted-client attestation, not cryptographic proof of a human.

A repeated identical authorization ID returns its original receipt without renewing budget or reclaiming control. Natural lease expiry can be recovered with `phone_wait` and a fresh observation. Manual takeover, pause, disconnect, server restart and grant expiry revoke the grant. Completion returns human ownership and does not start older queued tasks. Mopu does not launch an AI model.

Pending deliveries block later input. Fresh evidence must resolve them; no automatic send replay or duplicate destination attempt is allowed. The broker validates provenance, while the assistant remains responsible for interpreting screen contents and honoring the user's scope. Existing tasks are not migrated automatically.

## Legacy finite-stage mode

The following contract is retained for tasks using manual continuation. New whole-task work does not need repeated stage approvals.

## Contract

A continuation is a **finite human-approved stage of the same task**, not a retry that resets the counter. The existing 200-call stop remains. A user may approve another stage of 2–200 calls and 0–20 outgoing items (0 forbids sends), with an explicit scope and review note. Cumulative calls are `prior_steps + steps`; neither field is reset by continuation. Each review has an immutable identity, start total, absolute ceiling, task-state digest, expiry, and lifecycle state. Historic receipts/milestones/attempts remain intact. A stage ceiling is not automatic permission for the next stage.

The limit is tool calls, including reads, not messages. A `phone_step` reserves enough remaining budget before any input for its input, optional exact-target refresh, and maximum requested readbacks. It does not charge unused reads. A final delivery receipt may be sealed at exactly the ceiling without consuming another device call. A missing readback never counts as delivery.

## Human workflow

1. Take over the console. Wait for in-flight work to settle. Open the original stopped task, inspect checkpoint, previous results, total calls, delivery ledger, and pending item.
2. Select **人工检查并批准有限阶段**. Enter a review conclusion, finite scope/stop condition, call budget, and item limit; affirm progress/deduplication and last-action/uncertainty checks.
3. Submit. The broker rejects a stale task digest or control generation, a live lease, non-human ownership, repeated approval, invalid bounds, or missing checks. Approval itself leaves human ownership unchanged and does not launch a model or connect a phone.
4. Explicitly hand back. The original assistant claims its normal 120-second lease, reads current state, and follows the approved scope. The approval is consumed once on activation. Lease expiry alone does not replenish the stage.
5. After at most 30 minutes, budget exhaustion, takeover/pause, disconnect, restart, or human input following approval, further work requires a new human review. Unused allowance is not added to the next stage. A stopped model is still stopped; queueing is not execution.

Approval is implemented only on the existing authenticated **human console** control route, not as an MCP tool or CLI shortcut. This is a local trusted-client boundary, not cryptographic proof of a human: the current single-user application shares a local bearer credential across its interfaces. A malicious local process holding that credential is outside this enforcement model. Assistants must not call the human route to impersonate review.

## Assistant workflow

- Use the existing task. Read its `reviews[-1].scope`, `continuation`, checkpoint and delivery ledger. Do not use generic retry, control-request, cancel, or a new task to bypass `needs_review`; the broker rejects these paths for exhausted tasks. It also blocks another pre-existing task of the same agent while an unresolved review hold exists. Unrelated agents' existing tasks remain independent. Different identities or semantically disguised duplicates are not globally detectable by this trusted-client prototype.
- Long-task mutations must use `phone_step`. Declare `input_kind: navigation` for navigation and preparation, or `input_kind: send` **for every outgoing send**, with a stable `delivery_key` identifying its destination. Raw mutation `phone_call`, input probes, and file-transfer routes cannot substitute for this workflow.
- Keys must be stable across stages. Do not change a key to evade a prior attempt. Existing business-level deduplication records remain required; legacy deliveries are not automatically fabricated into this ledger.
- The broker persists an uncertain delivery record **before dispatch**. While a delivery is pending, further mutations are rejected; screen reads remain possible within the current approval/budget.
- Use `phone_delivery_confirm` with `key`, `outcome: delivered|not_sent`, and fresh passed screen checks (`criterion`, minimal `observed`, `observation_id`, `passed`). Only actual sent/delivered/read status for the correct destination qualifies as delivered. A tool acknowledgement does not. The broker checks task/generation, freshness and post-mutation provenance; the assistant judges semantics.
- Uncertain sends stay pending, do not count, and cannot be repeated. Even a confirmed `not_sent` key is not automatically replayable. Resolving a pending send after takeover requires another human review, a new normal lease and new screen evidence.
- When budget expires with a pending send, the next approved stage must begin by observing and resolving it. The pending record survives restart and review. If it cannot be resolved by observation, stop and hand the ambiguity to the user; do not guess or clear it in storage.
- Final completion still requires fresh final evidence; any pending delivery forces `unverified`. Historic stage evidence is not a current-state receipt.

The broker cannot infer whether an arbitrary coordinate click is a send, enforce natural-language scope, or independently read the meaning of a screenshot. Accurate `input_kind`, destination keys, scope adherence and semantic checks remain trusted-assistant duties. These limits are visible in the protocol rather than hidden behind a “verified” label.

## Compatibility and rollback

Legacy stopped tasks with `steps >= 200` require review before continuation. Approval retains `steps`, `prior_steps`, history and original ID; no migration script rewrites live state. Ordinary non-budget recovery remains compatible. Once a task enters formal long-task mode, generic retry cannot reset it. A verified completed task does not block future unrelated tasks.

This state extension is forward-only in operational terms: do not run an older broker on a queue containing formal reviews/delivery records. The older broker does not enforce the new approval rules. Preserve a pre-deployment queue backup, stop all execution, and reconcile post-deployment outcomes before any rollback; restoring an old queue blindly could replay work.


## Validation

See [0.19.1 validation](VALIDATION-0.19.1.md) for synthetic protocol and bounded physical-device evidence.
