# Task-scoped file transfers — stable protocol

This release retains the validated 4 MiB checkpoint implementation. Internal chunks are not a file-size limit. It does not include the separate 64 MiB throughput optimization or a `mobile_transfer_stop` tool.

Transfers use the existing broker, bound phone and exclusive lease. Use `phone_tools` for exact schemas, then `phone_call`. Freeze existing local source and destination directories with `mobile_transfer_scope`; they must be within configured `transfer_local_roots`. Symlinks and path traversal cannot expand this scope.

1. Check local disk headroom and `mobile_transfer_space`.
2. Freeze scope with `source_root`, `destination_root` and `user_authorization`.
3. Compute the source SHA256 and call `mobile_transfer_start` with `operation: push`, relative `source` and `sha256`.
4. Poll `mobile_transfer_job` with its `job_id` roughly every 30 seconds to maintain the lease. Progress is not checksum evidence. Use `operation: verify` with the transfer ID for complete phone checksum evidence.
5. Use `operation: pull`, `transfer_id` and a new relative `destination` to recover the file. Existing files are never overwritten; a temporary file is published only after full checksum agreement.
6. Preserve the phone copy until the intended recovery has actually been verified. `mobile_transfer_cleanup` requires the transfer ID and recovery evidence (or an explicit abandoned-test reason). Verify absence afterward.

`mobile_transfer_manifest` provides historical offsets, not fresh device evidence. `mobile_transfer_push` and `mobile_transfer_pull` expose single chunks for diagnostics; normal clients should use background start/job. `mobile_transfer_verify` offers immediate checksum checks for small files; timeouts never imply success.

Confirmed offsets survive restart. Background jobs stop on takeover, disconnect or lease expiry and do not restart automatically. Reissue the same transfer operation after an authorized recovery to resume its manifest. Task-created random phone directories are the only remote targets; cleanup is neither recursive nor wildcard-based. Original local files are never removed.

The broker does not verify cloud recovery. The calling assistant must substantiate the supplied recovery evidence. No cloud backup, Finder mount or phone-wide file access is implied.
