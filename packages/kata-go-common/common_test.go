package common

import "testing"

// Phase 0 smoke test: exercises the Go toolchain end-to-end. Real tests arrive in Phase 4.
func TestVersionIsSet(t *testing.T) {
	if Version == "" {
		t.Fatal("Version must not be empty")
	}
}

func TestComponentString(t *testing.T) {
	if got := IngestGateway.String(); got != "ingest-gateway" {
		t.Fatalf("IngestGateway.String() = %q, want %q", got, "ingest-gateway")
	}
}
