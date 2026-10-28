# Task management (0.18)

The console provides Task, Finished, and Trash views, keyword search across title/instruction/assistant, visible-result selection, single and batch pause/resume/delete/restore, and direct waiting-position selection. Editing keeps prior requirements. Known offline assistants remain available after restart; queuing never launches a model.

Delete is reversible: `deleted_at` hides a task from live and finished views and excludes it from scheduling. Original status, checkpoints, cumulative calls, receipts, delivery keys and uncertainty remain. Active stages close; a running deletion first revokes the lease, waits for in-flight input, and returns human control. No purge endpoint exists.

Restore removes the tombstone. Unfinished tasks become `user_held`; finished tasks stay finished. Resume clears only the hold flag. It does not clear needs_review, reset counters, grant a stage, change phone ownership or launch an assistant. The scheduler skips held/deleted tasks. Existing same-assistant review and duplicate-task protections still include retained deleted records; recovery of such work uses restore then the original finite-stage review.

Batch endpoints validate every target before changing records, including before interrupting a running task. Position changes affect only waiting slots and preserve running-task ownership; the UI submits its observed waiting order to detect stale changes. Management history persists.

UI acceptance uses isolated Console state with no device backend. Production installation must preserve all existing tasks and confirm no active lease/stage before restarting. Do not delete user tasks merely to test the feature.
