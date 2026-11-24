# ADR 0004: Transactional outbox for domain events

- Status: accepted
- Date: 2026-11-24

## Context

Phase 4 sends notifications (assignment, status changes, closure) over SMS, web push and the in-app inbox. If a request sends those directly, a crash after commit loses the message, and a send before a rollback reports something that never happened. Phase 3 already creates the first event that needs delivering (an issue being assigned), before any of the delivery code exists.

## Decision

- Domain events are rows in `outbox_events` (`tenant_id`, `event_type`, `aggregate_type`, `aggregate_id`, `payload` JSONB, `created_at`, `dispatched_at`), written **in the same transaction** as the change they describe. Either both commit or neither does.
- The table is tenant-scoped with row-level security like every other table. A partial index on `created_at WHERE dispatched_at IS NULL` keeps the dispatcher's scan cheap.
- Event names are `<aggregate>.<past-tense verb>`, e.g. `issue.assigned`. Payloads carry ids, not rendered text. The dispatcher looks up current data and the recipient's locale when it sends.
- Phase 3 writes rows only. In Phase 4, a dispatcher on the `default` queue claims undispatched rows (`FOR UPDATE SKIP LOCKED`), hands them to channel adapters and sets `dispatched_at`. Delivery is at-least-once, so consumers de-duplicate on the event `id`.

## Consequences

- No event is lost or sent for a rolled-back change, at the cost of a delay of up to one dispatcher tick.
- The table grows. Phase 4 adds retention for dispatched rows.
