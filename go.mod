// Single Go module for the whole Kata monorepo (ingest-gateway, outbox-relay,
// notifier, scan-runner agent, and the shared kata-go-common package).
// Phase 0: only kata-go-common has code; service mains arrive in Phase 4+.
module github.com/kata/kata

go 1.22
