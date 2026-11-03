# ADR-0005: RBAC model — effective access table; roles as text, not a PG enum

- Status: accepted
- Date: 2026-11-03

## Context

RBAC must be enforced in the data layer: every finding query is scoped to the products the
principal may see (project.md 2.8). Roles (Reader, API Importer, Writer, Maintainer, Owner)
apply globally, at the product-type level, and at the product level. Two sub-decisions:
(a) how to make the per-query scope check cheap, and (b) how to store the role value.

## Decision

**(a) Effective-access table.** `core.user_product_access(user_id, product_id, role)` holds
the *effective* access, recomputed from direct product memberships and product-type
memberships (`recompute_user_product_access`, set-based). Every finding query filters
`product_id IN (SELECT product_id FROM user_product_access WHERE user_id = :uid)` — one
indexed predicate, not a recursive walk of the hierarchy. Global read-all roles short-circuit
the filter entirely. This is the application-layer-filter option from 2.8 (chosen over
PostgreSQL RLS for debuggability), funnelled through one `list_findings` builder so no query
can forget the filter.

**(b) Roles as `text` + CHECK, not a PG enum.** Role columns use `text` with a CHECK against
the allowed set. Enums are costly to extend (`ALTER TYPE ... ADD VALUE` can't run in a
transaction with other DDL, can't remove values); the role set is more likely to evolve than
severity/status. Severity and status stay native enums because they are stable and benefit
from native ordering.

## Consequences

- Easier: scope checks are a single indexed `IN`; adding a role is a CHECK change; the filter
  lives in exactly one query builder that every caller uses.
- Harder: `user_product_access` must be kept in sync on membership change (and invalidated in
  the Valkey cache — Phase 1 Week 2 wiring). Staleness window on revocation is bounded by the
  cache TTL; immediate revocation deletes the row and busts the cache.
- Must monitor: any new finding query must go through `list_findings` / carry the RBAC
  predicate; a test asserts cross-tenant reads return empty.

## How DefectDojo does it

Global roles plus Product/Product-Type memberships, enforced in application code. Kata mirrors
the model and makes the effective set an explicit, indexed table.

## Revisit when

The recompute cost or cache staleness becomes a problem, or RLS becomes worth its debugging
cost (e.g. for defense-in-depth against a query that bypasses the builder).
