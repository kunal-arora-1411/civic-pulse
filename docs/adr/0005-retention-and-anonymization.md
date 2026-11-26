# ADR 0005: Retention and account anonymization

**Status:** accepted (periods pending the product owner's decision, due 8 Feb)
**Date:** 26 November 2026

## Context

PRD §12.2 asks for configurable retention and deletion, and §16 for
anonymizing a citizen without breaking the issues their reports belong to.
Reports are never deleted (§10.2), and issues, support, assignments and the
append-only audit log all reference users. The retention periods themselves
are not decided yet.

## Decision

1. **Anonymize, don't delete, users.** The row stays; what identifies the
   person is wiped (phone, email, name, preferences, MFA secret, session
   IPs and user agents, the private EXIF of their photos). Citizens do it
   themselves from the profile; staff accounts are deactivated by an admin.
2. **Placeholder phone under +999.** `users.phone` is NOT NULL, E.164-checked
   and unique per tenant, and the login upsert targets that constraint. A
   random number under +999 (reserved by ITU-T, never assigned) keeps all
   three without a schema change, can't receive SMS and can't collide with a
   real number. Logging in again with the old number creates a new account.
3. **Originals expire; variants stay.** The original upload holds full EXIF
   (GPS, device) and unblurred faces. A housekeeping step deletes it after
   `MEDIA_ORIGINAL_RETENTION_DAYS` and records `original_purged_at`; the
   stripped, face-checked variants remain as the public record. Default 0
   (off) until the periods are agreed.
4. **The audit log is not rewritten.** It is append-only by design (a
   trigger forbids UPDATE and DELETE). Events record actions and IDs; any
   personal data an older event holds (an email in a profile change, for
   example) stays until audit retention is decided with the hash chain
   (A6.3).

## Consequences

- Report text and locations are kept: they are the civic record. A citizen
  who wrote their own name into a description is not covered; moderation
  can redact text.
- Backups keep pre-anonymization data until they age out (14 days hourly,
  90 days daily; see `docs/runbooks/backup-restore.md`).
- Re-hashing (reindex) skips purged originals.
