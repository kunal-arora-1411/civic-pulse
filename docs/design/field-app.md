# Field app: UX design (B1.3)

**Status:** draft for review · **Owner:** frontend (B) · **Reviewers:** a field supervisor, backend (A) for the Phase 3 contract
**Covers:** PRD FR-063 to FR-066, FR-069, FR-070, §9.3; implementation plan P3-03, P3-04, P3-13

This is the design that B2.1 (queue and detail), B3.1 (closure) and B6.2 (offline queue) build against. The last section lists what the Phase 3 contract (A1.3) needs to provide.

---

## 1. Who and where

| | |
|---|---|
| **User** | Field worker on a municipal crew (roads, sanitation, electrical, parks). Often on a shared or low-end Android phone, sometimes with gloves or in sun glare. |
| **Context** | Standing at the site, one hand busy, patchy 2G/3G, battery matters. Switches between this app, the camera and Maps. |
| **Job to be done** | Know what's assigned to me, get there, do the work, prove it's done, move on. |
| **What they must never see** | Reporter name, phone, account or anything outside their assigned work (PRD §4.1, §9.3). |

## 2. Design principles

1. **One-handed at 360 px.** Primary actions sit in a sticky bottom bar within thumb reach. Tap targets are at least 48 × 48 px, with at least 8 px between them.
2. **Every action has a visible "queued" state.** Pressing a button never looks like nothing happened. Each action shows *Queued → Sending → Sent* or *Failed, retry*. This is designed in from day one even though full offline support lands in S6 (B6.2).
3. **Status is text plus icon, never colour alone.** The status chips reuse `StatusBadge` and add work-order states.
4. **Minimal data.** Show the problem, place, photos and instructions. Show no citizen identity.
5. **Bilingual parity.** Every label ships in English and Hindi. Hindi strings run roughly 30% longer, so layouts wrap rather than truncate.
6. **Cheap on data.** List thumbnails are 96 px. The mini-map is lazy and loads only on the detail screen, behind a "Show map" tap when Save Data is on.

## 3. Work order lifecycle (what the UI shows)

```
              assign
 (supervisor) ──────► ASSIGNED ──decline(reason)──► DECLINED  (back to supervisor)
                          │
                       accept
                          ▼
                      ACCEPTED ──start──► IN PROGRESS ──progress note──┐
                                              │  ▲                      │
                                              │  └──────────────────────┘
                                   request closure (after photo + reason)
                                              ▼
                                   CLOSURE REQUESTED ──approve──► DONE
                                              │
                                          reject(reason)
                                              ▼
                                         IN PROGRESS (with the supervisor's reason shown on top)
```

Queue tabs map to these states: **New** (assigned) · **Accepted** · **In progress** (includes closure-rejected) · **Done** (closure requested + done, last 7 days).

## 4. Screens

### 4.1 Work queue (`/field`)

```
┌──────────────────────────────────┐  360 px
│ ▣ CivicPulse  FIELD     EN ▾ (R) │  ink header
├──────────────────────────────────┤
│ FIELD                            │  eyebrow
│ My work orders                   │
│ Roads crew 7 · Ward 42           │
│                                  │
│ [New 3] [Accepted 2] [Active 1] [Done]  ← scrollable tabs, counts
│                                  │
│ ⚠ 1 update waiting to send  Retry│  only when something is queued
│                                  │
│ ┌──────────────────────────────┐ │
│ │[img] Pothole        ⏱ Due 4h │ │  SLA chip: icon + text
│ │      Near bus stop, MG Rd    │ │
│ │      CP-26-002611 · 1.2 km   │ │  distance if location allowed
│ │      ● New                   │ │
│ └──────────────────────────────┘ │
│ ┌──────────────────────────────┐ │
│ │[img] Blocked drain  ⚠ Overdue│ │
│ │      Sector 7, Ward 42       │ │
│ │      CP-26-002598 · 3.4 km   │ │
│ │      ● Accepted              │ │
│ └──────────────────────────────┘ │
│            ⟳ pull to refresh     │
└──────────────────────────────────┘
```

- Sorted by overdue first, then due time, then distance.
- Filters live behind a "Filter" chip: category, due today, overdue. They're kept in the URL so a supervisor can send a link.
- Empty states per tab ("Nothing new. Jobs assigned to you will appear here."). The current placeholder becomes the "New" empty state.
- Last-updated time sits under the tabs ("Updated 2 min ago"), so stale data is obvious when offline.

### 4.2 Work order detail (`/field/work-orders/[id]`)

```
┌──────────────────────────────────┐
│ ← Back           CP-26-002611    │
├──────────────────────────────────┤
│ ● New     ⏱ Due in 4h            │
│ Pothole                          │  large title
│ Near bus stop, MG Road           │
│ Ward 42 · Sector 7               │
│                                  │
│ ┌──────────────────────────────┐ │
│ │       [ mini-map, lazy ]     │ │  tap → full map
│ └──────────────────────────────┘ │
│ [ ↗ Directions ]  [ ⧉ Copy address ]
│                                  │
│ PHOTOS                           │
│ [img][img][img] →                │  citizen photos, faces blurred
│                                  │
│ DESCRIPTION                      │
│ Deep pothole outside the bus     │
│ stop, bikes are swerving round.  │
│                                  │
│ INSTRUCTIONS FROM SUPERVISOR     │  internal note, distinct styling
│ Bring cold-mix; barricade first. │
│                                  │
│ HISTORY                          │
│ • Assigned to you · 09:12        │
│                                  │
├──────────────────────────────────┤
│ [ Decline ]      [ Accept job  ] │  sticky action bar
└──────────────────────────────────┘
```

The sticky action bar changes with the state:

| State | Secondary | Primary |
|---|---|---|
| Assigned | Decline | **Accept job** |
| Accepted | Add note | **Start work** |
| In progress | Add note · Add photo | **Request closure** |
| Closure requested | Add note | *(none; shows "Waiting for supervisor")* |

- The **Directions** link opens `geo:` on Android or `https://maps.google.com/?daddr=lat,lng`. No in-app routing.
- The **reporter** never appears. Where history would say "Reported by …", it says "Reported by a citizen".

### 4.3 Decline (bottom sheet)

```
┌──────────────────────────────────┐
│ Decline this job?                │
│ Your supervisor will reassign it.│
│                                  │
│ ( ) Not my area                  │  reasons come from the API
│ ( ) Needs different equipment    │  (configurable per tenant)
│ ( ) Already fixed                │
│ ( ) Other                        │
│ [ Tell your supervisor why… ]    │  required for "Other"
│                                  │
│ [ Cancel ]        [ Decline ]    │
└──────────────────────────────────┘
```

### 4.4 Progress note (bottom sheet)

A text area of 500 characters max, with optional voice input later (B6.4), an optional photo (purpose `work_evidence`, kind `progress`) and a "Share my location" toggle (FR-065: optional location), off by default. Sending adds the note to the timeline immediately with a *Queued* tag.

### 4.5 Request closure (full screen, B3.1)

```
┌──────────────────────────────────┐
│ ✕  Request closure      Step 1/2 │
├──────────────────────────────────┤
│ BEFORE                AFTER      │
│ ┌──────────┐   ┌──────────────┐  │
│ │ [photo]  │   │   📷 Take    │  │  "before" pre-filled from
│ │ 09:40    │   │ after photo  │  │  start-work photo or the
│ └──────────┘   └──────────────┘  │  citizen photo; replaceable
│                                  │
│ Stand where the before photo was │  framing hint
│ taken so they can be compared.   │
│                                  │
├──────────────────────────────────┤
│                  [ Next → ]      │  disabled until "after" exists
└──────────────────────────────────┘

┌──────────────────────────────────┐
│ ←  Request closure      Step 2/2 │
├──────────────────────────────────┤
│ [before] ⇆ [after]   side by side│
│                                  │
│ What was done?                   │
│ (•) Repaired                     │  closure reasons from the API
│ ( ) Temporary fix                │
│ ( ) Not fixable – needs project  │
│ [ Notes for supervisor… ]        │
│                                  │
│ ⓘ Your supervisor reviews this   │
│   before the citizen is told.    │
├──────────────────────────────────┤
│           [ Send for approval ]  │
└──────────────────────────────────┘
```

- Capture uses `<input type="file" accept="image/*" capture="environment">`. It is the most reliable option on low-end Android and opens the native camera.
- Photos go through the existing upload pipeline (compression, progress, retry) with purpose `work_evidence`. Capture time comes from the device clock and EXIF if present, and location only if the worker allowed it (FR-066).
- The upload runs in the background while the worker fills in step 2, so "Send" doesn't wait on a slow upload unless it has to.

### 4.6 Rejected closure

The detail screen shows a warning banner at the top: "Closure not approved: *‹supervisor's reason›*". The primary action goes back to **Request closure**.

## 5. Connectivity states (designed now, built fully in B6.2)

Every action produces a local entry before any network call:

| State | What the user sees |
|---|---|
| **Queued** | Clock icon + "Queued, will send when online" on the timeline entry; a counter banner on the queue |
| **Sending** | Spinner + "Sending…" |
| **Sent** | Entry turns normal; toast "Accepted" (polite live region) |
| **Failed (retryable)** | "Couldn't send. Retry" with a button; kept in queue |
| **Conflict (409)** | "This job changed while you were offline" → the reconcile screen (B3.5): shows theirs vs yours and lets the worker choose |

Until B6.2 lands, actions are online-only, but they already render these states (Queued is skipped). Each action sends an `Idempotency-Key`, so a retry never duplicates an accept or a note.

## 6. Accessibility checklist (WCAG 2.2 AA)

- Target size ≥ 48 px for primary actions (2.5.8 asks for 24, but gloves need more).
- The sticky action bar doesn't cover focused content (2.4.11 focus not obscured): add bottom padding equal to the bar's height.
- Bottom sheets are native `<dialog>` (the existing `Dialog` primitive), so focus is trapped and returned.
- Status and SLA chips have text. The "Overdue" chip uses an icon as well as colour.
- Photo comparison: both images have alt text ("Before, taken 09:40", "After, taken 11:05").
- Pull-to-refresh also has a visible "Refresh" button (dragging must not be the only way, 2.5.7).

## 7. What the Phase 3 contract (A1.3) needs to give the field app

Please cover these in `docs/api/phase-3-contract.md`:

1. **`GET /field/work-orders`** filtered by `state` (repeatable), with `total` per state (for tab counts) and `version`. It needs these fields: reference, category, address text, ward, location `[lng, lat]`, due time and SLA state, and thumb URL. No distance is needed; the client computes it.
2. **`GET /field/work-orders/{id}`**: the above, plus photos (public variants only), description, internal instructions (visibility `internal`), a timeline with no reporter identity, `allowed_actions`, and `version`.
3. **Actions** as `POST /field/work-orders/{id}/{accept|decline|start|notes|closure-request}`, each taking `Idempotency-Key` and `If-Match: <version>` (or `version` in the body), and returning the updated work order. **409 `conflict`** must include the current server copy for the reconcile screen.
4. **Reason lists:** `GET /config/decline-reasons` and `GET /config/closure-reasons`, localized (`name_i18n`).
5. **Evidence:** the upload `purpose=work_evidence` with `kind` `before | after | progress`. Is capture time a client-supplied field, or read from EXIF on the server?
6. **Closure rejection:** the reject reason must be readable by the field worker on the work order.
7. **Privacy test:** a field worker reading a work order not assigned to them gets 404 (not 403), and no payload contains reporter PII.

## 8. Open questions for the product owner / field supervisor

- Can a worker accept several jobs and choose the order, or does the supervisor set the order?
- Is a **before** photo mandatory at "Start work" for some categories (e.g. roads), or is the citizen photo enough?
- Should a worker be able to **hand back** an accepted job (not just decline a new one)? The PRD mentions "request reassignment" (§6.3 step 18).
- Who sees the progress notes: internal only, or can a worker post a public update ("Crew on site")?
