// Package common holds Kata's shared Go building blocks: auth, telemetry and Kafka
// helpers used by the ingest-gateway, outbox-relay, notifier and scan-runner agent.
//
// Phase 0: skeleton only. Real helpers arrive alongside the ingestion plane in Phase 4.
package common

// Version is the current version of the Kata Go components.
const Version = "0.0.0"

// Component names the Kata Go services that share this package. Used for logging and
// telemetry resource attributes once those helpers land in Phase 4.
type Component string

const (
	IngestGateway Component = "ingest-gateway"
	OutboxRelay   Component = "outbox-relay"
	Notifier      Component = "notifier"
	ScanRunner    Component = "scan-runner"
)

// String returns the component's name.
func (c Component) String() string { return string(c) }
