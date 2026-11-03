# ADR-0008: Return 404 (not 403) for resources the principal may not see

- Status: accepted
- Date: 2026-11-03

## Context

When a principal requests a product/finding they have no access to, the API can return 403
(Forbidden — "it exists, you can't have it") or 404 (Not Found — "no such thing for you").
403 leaks existence: an attacker can enumerate which product/finding IDs exist by status code.

## Decision

For resources scoped by RBAC (products, findings and their children), **return 404 when the
principal has no read access** — identical to a genuinely missing ID. 403 is reserved for the
case where the principal *can read* the resource but lacks the role for the *action* (e.g. a
Reader attempting a transition on a finding they can see). In short:

- No read access → **404** (no existence leak).
- Read access but insufficient role for the write → **403**.

This is implemented via `get_finding_authorized` / `effective_role`: a `None` role means 404;
a present-but-too-low role means 403.

## Consequences

- Easier: no ID enumeration via status codes; the list endpoint already returns only visible
  rows, so detail endpoints stay consistent with it.
- Harder: a legitimate user with a typo can't tell "wrong id" from "no access" — acceptable
  for a security tool.
- Must monitor: every RBAC-scoped detail/mutation endpoint must use the authorized fetch, not
  a raw `session.get` followed by a 403.

## How DefectDojo does it

DefectDojo's object-permission checks generally yield 403/404 depending on the view; Kata
standardises on 404-for-no-access across the API. Recorded in the parity doc.

## Revisit when

A product need requires distinguishing "missing" from "forbidden" for read access (none so far).
