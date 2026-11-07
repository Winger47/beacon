"""Phase 3 reimport parity harness (project.md Part V, Phase 3 Week 3).

Runs a fixed *sequence* of import/reimport steps and compares the create / untouched /
reactivate / close counts produced by each configured backend against a backend-independent
oracle computed from the sequence itself. DefectDojo is an optional second backend: point the
harness at a live instance with ``DEFECTDOJO_URL`` + ``DEFECTDOJO_TOKEN`` and its counts are
diffed too. See docs/parity.md for the backends and every intentional difference.
"""
