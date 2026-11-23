
# **CIVICPULSE**

## Product Requirements Document

_AI-powered Civic Intelligence & Resolution Platform_

|**Document field**|**Value**|
|---|---|
|Document version|1.0|
|Status|Product definition|
|Prepared on|23 November 2026|
|Product category|Civic technology / GovTech / AI-enabled workflow platform|
|Primary users|Citizens, municipal administrators, field teams, platform<br>administrators|
|Product principle|Turn individual citizen reports into verified, prioritized and<br>trackable civic issues.|

**Tagline: Turning citizen complaints into actionable civic intelligence.**

### **Document guide**

- 1. Product overview

- 2. Problem statement and opportunity

- 3. Product goals and success measures

- 4. Users, roles and permissions

- 5. Scope and product boundaries

- 6. End-to-end workflows

- 7. Functional requirements

- 8. AI and intelligence requirements

- 9. User experience requirements

- 10. Data model and business rules

- 11. API and integration requirements

- 12. Security, privacy and governance

- 13. Non-functional requirements

- 14. Analytics and reporting

- 15. Notifications and communications

- 16. Error handling and edge cases

- 17. Acceptance criteria

- 18. Assumptions, dependencies and open decisions

- Appendix A. Suggested technology architecture

- Appendix B. Glossary

### **1. Product overview**

CivicPulse is a civic issue reporting, intelligence and resolution platform. It enables citizens to report public infrastructure and sanitation problems using photographs, descriptions and geolocation. The platform uses AI-assisted classification, geospatial proximity and image similarity to identify potentially duplicate reports and associate them with a consolidated underlying civic issue. It prioritizes issues using configurable severity and impact rules, then gives municipal administrators tools to review, assign, track and close issues. Citizens can follow progress and provide community verification of reported resolutions.

CivicPulse is designed as a complete product specification, not a time-boxed prototype plan. Requirements below describe the intended product capability set. Individual deployments may configure categories, workflows, service-level targets, languages, jurisdictions and integrations.

#### **1.1 Product vision**

Create a trusted civic operations layer that converts fragmented citizen feedback into structured, location-aware work items, helps authorities act on the most important problems first, and makes progress visible to the public.

#### **1.2 Product principles**

- One underlying issue may have many citizen reports; reports and issues must remain separate concepts.

- AI should assist classification and prioritization, not make unreviewable public-service decisions.

- Location, evidence, timestamps and status history should make each issue auditable.

- Citizens should be able to report and track an issue with minimal effort, including on low-bandwidth devices.

- Authorities need operational tools, not just a map of complaints.

- Public transparency must coexist with privacy, abuse prevention and data minimization.

### **2. Problem statement and opportunity**

Citizens commonly report potholes, waterlogging, waste accumulation, damaged streetlights, blocked drains and similar public issues through multiple channels. Reports about the same physical problem can be fragmented across people, locations and time. This can create duplicate workload, obscure the scale of a problem, make prioritization difficult and leave citizens uncertain about whether action has been taken.

#### **2.1 Product response**

- Capture structured reports with media, category, description, time and geolocation.

- Detect likely issue categories from submitted evidence and allow correction.

- Identify candidate duplicates using location, image similarity, category and time.

- Consolidate related reports under a single civic issue while preserving each original report.

- Calculate transparent, configurable priority scores and surface hotspots.

- Support assignment, field updates, evidence-based resolution and citizen verification.

- Provide analytics that help administrators understand demand, response and recurring problems.

### **3. Product goals and success measures**

#### **3.1 Goals**

- Make civic issue reporting accessible and simple for citizens.

- Reduce duplicate operational records through accurate report-to-issue association.

- Improve issue triage through consistent classification and severity assessment.

- Give administrators a single operational view of incoming and unresolved issues.

- Improve transparency through status history and resolution evidence.

- Provide reliable data for ward-level and category-level planning.

#### **3.2 Success measures**

|**Measure**|**Definition**|**How to evaluate**|
|---|---|---|
|Report completion rate|Share of started reports successfully submitted.|Completed submissions / report starts.|
|Classification quality|Correctness of AI-suggested issue categories.|Labeled test set; per-class precision, recall and<br>F1.|
|Duplicate precision|Share of reports auto-linked as duplicates that<br>truly refer to the same issue.|Manually labeled duplicate evaluation set.|
|Duplicate recall|Share of known duplicate reports correctly<br>associated.|Manually labeled duplicate evaluation set.|
|False merge rate|Share of distinct issues incorrectly merged.|Adversarial and location-nearby test cases.|
|Triage time|Time from submission to an actionable issue<br>record.|Application event timestamps.|
|Resolution time|Time from issue creation to verified closure.|Issue lifecycle timestamps.|
|Reopen rate|Share of closed issues subsequently reopened.|Issue status history.|
|Citizen satisfaction|Citizen feedback on reporting and resolution<br>experience.|Optional post-resolution survey.|
|Operational workload|Number of individual reports grouped into<br>consolidated issues.|Report-to-issue relationship analytics.|

_Targets must be agreed with the deploying authority after baseline measurement. CivicPulse must not present unvalidated prototype metrics as real-world impact._

### **4. Users, roles and permissions**

|**Role**|**Primary responsibilities**|**Key permissions**|
|---|---|---|
|Citizen|Submit reports, follow issues, add supporting<br>evidence and verify outcomes.|Create reports; view own reports and public<br>issue details; comment or verify subject to<br>policy.|
|Verified community contributor|Provide additional evidence and community<br>confirmation.|Citizen permissions plus configurable<br>verification actions.|
|Municipal operator / triage officer|Review reports, correct classifications, manage<br>issue records and prioritize work.|View assigned jurisdiction; merge/split with<br>audit; edit issue details; change triage status.|
|Department supervisor|Oversee workload, assign teams, monitor<br>service levels and approve closure where<br>required.|Assign/reassign; set priority; approve/reject<br>closure; view department analytics.|
|Field team member|Receive work orders, update progress and<br>submit completion evidence.|View assigned tasks; accept work; update<br>progress; upload evidence; request closure.|
|Municipal administrator|Configure jurisdiction, categories, teams,<br>service rules and users.|Manage municipal configuration, roles, service<br>areas and reports.|
|Platform administrator|Operate the CivicPulse tenant and platform.|Tenant provisioning, system configuration,<br>security and operational monitoring.|

#### **4.1 Authorization principles**

- Role-based access control must be enforced on the server for every protected operation.

- Municipal users must be scoped to their organization, department and authorized geographic jurisdiction.

- Field team members must only access assigned work orders and the minimum information needed to perform work.

- Citizens must not see private personal information belonging to other citizens.

- Platform administrators must not receive routine access to citizen content unless required for support, security or lawful operations; such access must be logged.

### **5. Scope and product boundaries**

#### **5.1 In scope**

- Citizen-facing responsive web application / installable PWA.

- Municipal administration and operations dashboard.

- Field team task interface.

- Issue reporting with image, text, optional voice input and geolocation.

- AI-assisted classification and duplicate detection.

- Priority scoring, geospatial clustering and hotspot analytics.

- Issue assignment, status lifecycle, evidence and community verification.

- Notifications, audit trail, search, filters and reporting.

- Tenant, jurisdiction, role, category and workflow configuration.

- API and integration layer for future municipal systems.

#### **5.2 Out of scope unless separately commissioned**

- Automatic dispatch of public works vehicles or emergency services.

- Direct control of municipal infrastructure or IoT devices.

- Guaranteed integration with any government grievance portal or municipal ERP.

- Automated legal determination of responsibility or liability.

- Automated fines, enforcement actions or citizen identity scoring.

- A guarantee that a complaint will be resolved within a particular time.

- Unsupervised AI decisions that permanently close, reject or merge high-impact issues.

### **6. End-to-end workflows**

#### **6.1 Citizen report submission**

1. Citizen opens the application and chooses a supported issue category or selects AI-assisted identification.

2. Citizen captures or uploads one or more photographs and optionally enters a description or voice note.

3. Application requests location permission or allows manual pin placement and address correction.

4. System validates file type, file size, metadata and required fields.

5. System stores the media securely and creates a report record.

6. AI service proposes a category and confidence score; the citizen can correct the category.

7. Deduplication service searches for candidate civic issues and computes a match score.

8. The report is linked to an existing issue, sent for human review, or used to create a new issue.

9. Citizen receives a report reference and can view the resulting issue status.

#### **6.2 Triage and consolidation**

10. Triage officer sees new reports and suggested issue associations.

11. The officer can accept or reject an AI-suggested association.

12. The officer can merge two issue records when they represent the same physical problem.

13. The officer can split an incorrectly consolidated issue and reassign reports.

14. All merge, split and reassignment actions must preserve history and actor identity.

15. The system recalculates report counts and priority after relevant changes.

#### **6.3 Assignment and field resolution**

16. Supervisor selects an issue and assigns it to a department, team or field worker.

17. Assigned personnel receive a notification and view the work order.

18. Field personnel accept, reject with a reason, or request reassignment.

19. Field personnel update progress and may add notes, photographs and completion evidence.

20. Authorized personnel request closure; the issue moves to pending verification or approval.

21. Citizen/community verification or authorized supervisor review determines final closure according to configured policy.

22. If the issue remains unresolved or evidence is inadequate, it can be rejected for closure or reopened.

#### **6.4 Analytics and planning**

Administrators filter issues by geography, category, severity, status, department and time. The dashboard aggregates reports into issue-level views and displays hotspot patterns, workload, ageing, resolution time and recurring locations.

### **7. Functional requirements**

#### **7.1 Identity, onboarding and account management**

**FR-001 — Citizen registration [Must]** The system shall support citizen account creation using configured identity methods such as phone OTP, email verification or approved single sign-on.

**FR-002 — Guest reporting configuration [Should]** The system should allow a deployment to enable limited guest reporting. Guest reports must use abuse controls and may have reduced tracking or verification capabilities.

**FR-003 — Profile management [Must]** Users shall be able to view and update permitted profile fields, communication preferences and language preferences.

**FR-004 — Account recovery [Must]** The system shall provide secure account recovery and session revocation.

**FR-005 — Role and organization management [Must]** Administrators shall create, disable and assign roles to municipal operators, supervisors and field personnel.

**FR-006 — Jurisdiction scoping [Must]** Municipal users shall only access records within their authorized tenant, department and geographic scope.

#### **7.2 Citizen reporting**

**FR-007 — Create report [Must]** A citizen shall be able to submit a report with category, location and at least one supported evidence or description field, according to deployment policy.

**FR-008 — Image and video evidence [Must]** The application shall support configurable image formats and size limits. Video support may be enabled by deployment policy.

**FR-009 — Multiple attachments [Must]** A report may contain multiple images and supporting files, subject to security and storage limits.

**FR-010 — Location capture [Must]** The application shall capture device location with consent and allow the user to adjust the map pin or enter a location manually.

**FR-011 — Address resolution [Should]** The system should resolve coordinates to a readable address when a configured geocoding provider is available.

**FR-012 — Description input [Must]** Citizens shall be able to enter free-text descriptions and optional structured details.

**FR-013 — Voice input [Should]** The application should support voice notes or speech-to-text in configured languages, with the transcript editable before submission.

**FR-014 — Draft saving [Should]** The application should allow a report draft to be saved locally or server-side and resumed later.

**FR-015 — Submission confirmation [Must]** The system shall issue a unique report reference and show the citizen whether the report was accepted, queued or requires correction.

**FR-016 — Report history [Must]** Citizens shall be able to view their own submitted reports, associated civic issue, status and update history.

**FR-017 — Additional evidence [Must]** Citizens shall be able to add evidence or comments to an existing issue, subject to moderation and rate limits.

**FR-018 — Report withdrawal [Should]** A citizen may request withdrawal of a report. Withdrawal shall not erase an issue record needed for audit; the system shall retain an appropriate tombstone or audit event.

#### **7.3 Issue categories and classification**

**FR-019 — Configurable categories [Must]** The system shall support administrator-managed categories and subcategories, initially including potholes/road damage, waste accumulation, waterlogging, streetlight failure and drainage hazards.

**FR-020 — AI category suggestion [Must]** The system shall analyze submitted evidence and suggest one or more issue categories with confidence values.

**FR-021 — Human correction [Must]** Citizens and authorized operators shall be able to correct a suggested category; corrections shall be logged and made available for model evaluation.

**FR-022 — Unknown or ambiguous category [Must]** When confidence is below a configured threshold or the input is unsupported, the system shall request manual selection or route the report to review.

**FR-023 — Category-specific fields [Should]** Administrators shall be able to configure additional fields for categories, such as road name, obstruction type or affected asset.

#### **7.4 Duplicate detection and issue consolidation**

**FR-024 — Candidate search [Must]** For each new report, the system shall search for potentially related open or recently closed issues within configurable geographic and temporal bounds.

**FR-025 — Geospatial similarity [Must]** The system shall calculate geographic proximity using coordinates and configurable distance thresholds.

**FR-026 — Visual similarity [Must]** The system shall generate image embeddings or equivalent visual descriptors and compare them with candidate reports/issues.

**FR-027 — Category compatibility [Must]** The system shall compare report categories and reject or reduce the score of incompatible candidates.

**FR-028 — Temporal relevance [Must]** The system shall account for report time and issue lifecycle when ranking candidate matches.

**FR-029 — Combined match score [Must]** The system shall compute a configurable combined score from geospatial, visual, category and temporal signals.

**FR-030 — Automatic association [Must]** Reports above a high-confidence threshold may be automatically associated with an existing issue when deployment policy permits.

**FR-031 — Human review queue [Must]** Ambiguous matches shall be placed in a review queue with candidate explanations and evidence.

**FR-032 — New issue creation [Must]** If no candidate is sufficiently similar, the system shall create a new civic issue and associate the report.

**FR-033 — Manual merge [Must]** Authorized operators shall be able to merge issue records, select a surviving issue and preserve the full report and audit history.

**FR-034 — Manual split [Must]** Authorized operators shall be able to split an issue and move selected reports into a new or existing issue.

**FR-035 — Duplicate feedback [Must]** Operators shall be able to mark a proposed match as correct or incorrect. This feedback shall be retained for quality analysis.

**FR-036 — Concurrency safety [Must]** Concurrent reports for the same location shall not create inconsistent report counts or duplicate issue associations. Database constraints, transactions or locking shall protect association operations.

**FR-037 — Explainable match details [Must]** The review interface shall show why a match was suggested, including distance, category compatibility, similarity score and relevant timestamps.

#### **7.5 Severity and priority management**

**FR-038 — Severity assessment [Must]** The system shall calculate or suggest severity using category-specific rules and evidence. Authorized operators shall be able to override it with a reason.

**FR-039 — Priority score [Must]** The system shall calculate a configurable priority score using severity, public safety risk, number of distinct reports, issue age, affected area and recurrence.

**FR-040 — Unique reporter count [Must]** The system shall distinguish unique reporting users from total report submissions to reduce manipulation by repeated submissions.

**FR-041 — Priority bands [Must]** Administrators shall configure priority bands such as critical, high, medium and low, including thresholds and escalation rules.

**FR-042 — Priority explanation [Must]** The system shall display the main factors contributing to an issue's priority.

**FR-043 — Manual override [Must]** Authorized operators shall be able to change priority and record the reason, actor and timestamp.

**FR-044 — Priority recalculation [Must]** Priority shall be recalculated when relevant report, severity, age, recurrence or verification data changes.

#### **7.6 Geospatial intelligence and hotspots**

**FR-045 — Issue map [Must]** The system shall display issues on an interactive map, subject to user permissions and location privacy settings.

**FR-046 — Map filters [Must]** Users shall be able to filter map results by category, priority, status, department, date range and jurisdiction.

**FR-047 — Hotspot aggregation [Must]** The system shall aggregate issue records into configurable geographic cells or clusters to identify concentration areas.

**FR-048 — Hotspot time comparison [Must]** Administrators shall be able to compare hotspot intensity across selected time periods.

**FR-049 — Recurring location detection [Should]** The system should identify locations with repeated issue creation or reopening.

**FR-050 — Map/list synchronization [Must]** Selecting a map marker or cluster shall show the corresponding issue list and details.

**FR-051 — Location privacy [Must]** Public maps shall use configurable precision or generalized locations where exact coordinates could expose sensitive information.

#### **7.7 Issue lifecycle and workflow**

**FR-052 — Configurable lifecycle [Must]** The system shall support a configurable lifecycle with states including reported, under review, verified, assigned, in progress, pending verification, resolved, rejected, closed and reopened. Default state meanings:

|**State**|**Meaning**|
|---|---|
|Reported|Issue record created from one or more reports; not yet reviewed by an operator.|
|Under review|An operator is checking classification, location, jurisdiction or duplicate association.|
|Verified|An operator has confirmed the issue is real, in jurisdiction and correctly categorized. It is ready to be<br>assigned. (Not to be confused with resolution verification in section 7.9.)|
|Assigned|Allocated to a department, team or individual; work not yet started.|
|In progress|Assigned personnel have accepted the work and started it.|
|Pending verification|Closure has been requested with evidence; awaiting supervisor approval and/or citizen or community<br>verification.|
|Resolved|Verification or approval succeeded. The issue stays open to negative citizen feedback for a configured<br>window (for example, 7 days).|
|Rejected|The report or issue was found invalid, out of jurisdiction, abusive or unsupported. A reason is recorded.|
|Closed|Final state. The resolution window has ended with no unresolved feedback, or a rejection is final.<br>Later recurrence creates a reopening request or a new linked issue under category policy.|
|Reopened|A resolved or closed issue was found to persist or recur. It returns to triage with its history kept.|

**FR-053 — Valid transitions [Must]** The system shall enforce role- and state-based transition rules.

**FR-054 — Status history [Must]** Every status change shall record previous state, new state, actor, timestamp and optional reason.

**FR-055 — Issue detail page [Must]** Each issue shall have a consolidated detail page showing reports, evidence, location, classification, priority, assignments, comments and history.

**FR-056 — SLA configuration [Must]** Administrators shall be able to configure target acknowledgement, assignment and resolution times by category, priority or jurisdiction.

**FR-057 — SLA ageing [Must]** The system shall show time elapsed, overdue status and upcoming SLA breaches.

**FR-058 — Reopen issue [Must]** Authorized users or eligible citizens shall be able to request reopening when the issue persists or reoccurs; policy shall determine whether reopening is automatic or reviewed.

**FR-059 — Reject report [Must]** Operators shall be able to reject invalid, out-of-jurisdiction, abusive or unsupported reports with a reason and appeal or resubmission guidance where configured.

**FR-060 — Issue relationship [Should]** The system should support linking related but distinct issues, such as multiple potholes along one road, without merging them.

#### **7.8 Assignment and field operations**

**FR-061 — Department and team setup [Must]** Administrators shall configure departments, service teams, service areas, working schedules and supported issue categories.

**FR-062 — Issue assignment [Must]** Supervisors shall assign or reassign an issue to a team or individual.

**FR-063 — Assignment acknowledgement [Must]** Assigned personnel shall be able to accept or decline a work order with a reason.

**FR-064 — Field work queue [Must]** Field personnel shall see assigned, accepted, in-progress and completed work orders.

**FR-065 — Field status updates [Must]** Field personnel shall update progress and provide notes, timestamps and optional location information.

**FR-066 — Before/after evidence [Must]** Field personnel shall upload completion photographs or other evidence, with capture time and optional location metadata.

**FR-067 — Work order notes [Must]** Authorized users shall be able to add internal notes distinct from public comments.

**FR-068 — Workload view [Must]** Supervisors shall be able to view team workload, overdue tasks and assignment distribution.

**FR-069 — Offline field capture [Should]** The field interface should allow selected updates and evidence to be queued offline and synchronized when connectivity returns.

#### **7.9 Resolution verification and community participation**

**FR-070 — Closure request [Must]** Field personnel or authorized operators shall be able to request closure with mandatory evidence or a configured closure reason.

**FR-071 — Supervisor approval [Must]** Deployments shall be able to require supervisor approval before an issue is closed.

**FR-072 — Citizen verification [Must]** Eligible citizens who reported or follow an issue shall be able to confirm resolution or report that the issue remains unresolved.

**FR-073 — Community verification [Must]** The system shall support configurable verification thresholds or rules without allowing a single untrusted account to determine closure. Default rule, configurable per deployment: an issue moves from pending verification to resolved when (a) an authorized supervisor approves it, or (b) at least two distinct eligible citizens (original reporters or followers with verified accounts) confirm resolution and none report it unresolved. Each verifier counts once per issue. A single "still unresolved" response from an eligible citizen sends the issue to review.

**FR-074 — Reopen workflow [Must]** Negative verification shall trigger a review or reopening workflow according to configured rules.

**FR-075 — Verification integrity [Must]** The system shall apply rate limits, account trust rules and abuse checks to verification actions.

#### **7.10 Search, filters and administration**

**FR-076 — Global issue search [Must]** Authorized users shall be able to search by issue ID, report ID, address, category, status and relevant text.

**FR-077 — Saved filters [Should]** Users should be able to save frequently used filter combinations.

**FR-078 — Bulk actions [Should]** Authorized administrators should be able to perform safe bulk assignment or status actions with confirmation and audit logging.

**FR-079 — Category configuration [Must]** Administrators shall manage categories, subcategories, required fields and supported evidence types.

**FR-080 — Jurisdiction configuration [Must]** Administrators shall configure municipal boundaries, wards, zones and service areas.

**FR-081 — Workflow configuration [Must]** Administrators shall configure status transitions, approval requirements, SLA rules and escalation policies.

**FR-082 — Tenant configuration [Must]** The platform shall support multiple municipal organizations with tenant-isolated data and configuration.

**FR-083 — Audit log [Must]** The system shall maintain searchable audit events for sensitive actions, administrative changes, merges, splits, assignment and status transitions.

#### **7.11 Public information and citizen engagement**

**FR-084 — Public issue view [Should]** The system may expose a public issue page containing non-sensitive details, generalized location, status and update history.

**FR-085 — Follow issue [Must]** Citizens shall be able to follow an issue and receive permitted status updates.

**FR-086 — Comments and moderation [Must]** Where public comments are enabled, the system shall support reporting, moderation, rate limiting and removal with an audit trail.

**FR-087 — Service announcements [Could]** Municipal administrators could be able to publish area- or category-specific service announcements.

### **8. AI and intelligence requirements**

#### **8.1 AI classification service**

- Accept image evidence through a secured inference interface.

- Return predicted category, confidence, model identifier and processing metadata.

- Support confidence thresholds and an unknown/needs-review outcome.

- Allow manual correction and record corrected labels for evaluation.

- Version models and retain model/version metadata with predictions.

- Avoid treating model confidence as proof that an issue exists or that a citizen's report is truthful.

#### **8.2 Visual similarity service**

- Generate embeddings for supported image types using a versioned model.

- Compare embeddings only among geographically and categorically plausible candidates where possible.

- Support configurable similarity metrics and thresholds.

- Store embedding model version to enable re-indexing when models change.

- Handle poor lighting, different camera angles, weather changes and low-quality images.

- Avoid relying on image similarity alone for issue merging.

#### **8.3 Hybrid duplicate matching**

A configurable score may combine the following signals:

|**Signal**|**Purpose**|**Example handling**|
|---|---|---|
|Geospatial similarity|Determine whether reports refer to nearby<br>physical locations.|Distance bands or spatial decay score.|
|Visual similarity|Compare the physical scene or asset shown<br>in images.|Cosine similarity between image<br>embeddings.|
|Category compatibility|Ensure reports describe compatible issue<br>types.|Exact match, compatible parent category or<br>mismatch penalty.|
|Temporal relevance|Account for issue persistence and report<br>age.|Decay or boost based on category-specific<br>time windows.|
|Text similarity|Compare descriptions and landmarks where<br>available.|Optional multilingual text embeddings.|

The final score and decision thresholds must be configurable. A high-confidence match may be auto-associated where enabled; a medium-confidence match should enter human review; a low-confidence match should create a new issue or remain unlinked. The system must retain the decision and contributing signals.

#### **8.4 Priority intelligence**

Priority scoring shall be rules-based and explainable. Inputs may include public safety severity, issue category, number of distinct reporters, issue age, recurrence, affected area, critical infrastructure proximity and SLA status. Weights and overrides must be configurable by jurisdiction. AI may recommend a score, but the platform must expose the factors and allow authorized human review.

#### **8.5 Administrative analytics assistant**

**AI-001 — Natural-language analytics [Should]** Authorized administrators should be able to ask questions about permitted operational data in natural language.

**AI-002 — Read-only tools [Must]** The assistant shall use approved, read-only analytics tools or parameterized queries; it shall not execute unrestricted generated SQL.

**AI-003 — Permission-aware responses [Must]** The assistant shall enforce the user's existing data scope and permissions.

**AI-004 — Grounded answers [Must]** Responses shall identify the reporting period, filters and data used, and state when data is insufficient.

**AI-005 — Action confirmation [Should]** Any future write action initiated through an assistant must require explicit confirmation and normal authorization checks.

#### **8.6 AI governance**

- Maintain a model registry or configuration record with model name, version, deployment date and intended use.

- Monitor per-category precision, recall, false-positive rates and drift.

- Provide human override and correction pathways.

- Do not infer sensitive personal attributes from citizen media or profiles.

- Do not use AI output as the sole basis for rejecting a citizen or closing a public issue.

- Provide a fallback manual workflow when the AI service is unavailable.

### **9. User experience requirements**

#### **9.1 Citizen experience**

- Mobile-first, responsive and installable as a PWA where supported.

- Short reporting flow with clear progress and plain-language labels.

- Accessible controls, readable contrast, keyboard support and screen-reader labels.

- Support configured Indian languages; language selection must be available without requiring account creation.

- Use icons and visual guidance where helpful, but do not rely on color alone to communicate status.

- Show location accuracy and allow pin correction.

- Provide upload progress, retry and clear error messages.

- Support low-bandwidth behavior, image compression and resumable or retryable uploads.

#### **9.2 Administration experience**

- Provide a work queue with sorting, filters, saved views and bulk operations.

- Show map and list views with synchronized selection.

- Make priority, SLA age, report count and assignment status visible.

- Explain AI suggestions and allow review without leaving the issue context.

- Keep internal notes separate from public updates.

- Provide keyboard-accessible tables and operational dashboards.

#### **9.3 Field team experience**

- Show assigned work, address, map location, issue description and relevant evidence.

- Make accept, decline, start work and request closure actions easy to access.

- Support image capture from the device and queued offline updates.

- Minimize unnecessary personal data exposure.

### **10. Data model and business rules**

#### **10.1 Core domain entities**

|**Entity**|**Description**|**Important attributes**|
|---|---|---|
|Tenant / Municipality|An organization using CivicPulse.|id, name, configuration, jurisdiction|
|User|Citizen, operator, supervisor, field worker or<br>platform user.|id, role, contact, tenant, preferences|
|Department / Team|Operational unit responsible for issue<br>categories or areas.|id, tenant, service area, categories|
|Report|An individual citizen submission.|id, reporter, issue_id, media, description,<br>location, timestamp|
|Civic Issue|The consolidated underlying real-world<br>problem.|id, category, severity, priority, status, location,<br>report_count|
|Media Asset|Image, video, audio or evidence file.|id, storage_key, type, checksum, metadata|
|Embedding / Prediction|Versioned AI output associated with media or<br>report.|model_version, vector, label, confidence|
|Assignment|Work allocated to a team or person.|issue_id, assignee, assigned_at, state|
|Issue Update|Status transition, comment or operational note.|issue_id, actor, event_type, timestamp, visibility|
|Verification|Citizen or supervisor assessment of a proposed<br>resolution.|issue_id, actor, outcome, timestamp|
|Audit Event|Immutable record of sensitive or administrative<br>actions.|actor, action, entity, before/after, timestamp|
|Notification|A message generated for a user or group.|recipient, channel, template, delivery_state|

#### **10.2 Core business rules**

- A report is not the same entity as a civic issue. Multiple reports may reference one issue.

- A report must not be silently deleted when an issue is merged or split.

- Every report must have a unique identifier and submission timestamp.

- An issue's report count must be derived or transactionally maintained and reconcile with associated reports.

- A user may submit multiple reports, but priority calculations should count distinct reporters separately.

- Only authorized roles may change issue status, assignment, severity or priority overrides.

- A resolved issue may be reopened when new evidence indicates the problem persists or has recurred.

- Merges and splits must preserve the original identifiers and complete audit history.

- Location may be approximate or manually entered; the system must retain location provenance and accuracy where available.

- Public views must not expose private reporter contact information or internal operational notes.

### **11. API and integration requirements**

#### **11.1 API conventions**

- Expose versioned REST APIs, for example /api/v1/.

- Use JSON for structured request and response bodies and multipart or pre-signed uploads for media.

- Use consistent error objects with machine-readable codes and human-readable messages.

- Support pagination, filtering, sorting and stable resource identifiers.

- Enforce authentication, authorization, validation, rate limits and request-size limits at the API boundary.

- Use idempotency keys for report creation and other retry-prone operations.

- Publish an OpenAPI specification and maintain API contract tests.

#### **11.2 Core API surface**

|**Method**|**Endpoint**|**Purpose**|
|---|---|---|
|POST|/api/v1/reports|Create a citizen report.|
|GET|/api/v1/reports/{report_id}|Retrieve a report and its linked issue.|
|GET|/api/v1/users/me/reports|List the current citizen's reports.|
|GET|/api/v1/issues|Search and filter civic issues.|
|GET|/api/v1/issues/{issue_id}|Retrieve consolidated issue details.|
|GET|/api/v1/issues/nearby|Find nearby candidate issues.|
|POST|/api/v1/issues/{issue_id}/merge|Merge issues with audit and validation.|
|POST|/api/v1/issues/{issue_id}/split|Split reports into separate issues.|
|POST|/api/v1/issues/{issue_id}/assignments|Assign an issue to a team or user.|
|PATCH|/api/v1/issues/{issue_id}/status|Transition issue status.|
|POST|/api/v1/issues/{issue_id}/verification|Submit citizen or supervisor verification.|
|GET|/api/v1/analytics/overview|Retrieve operational summary metrics.|
|GET|/api/v1/analytics/hotspots|Retrieve geospatial hotspot aggregates.|
|POST|/api/v1/ai/classifications|Request or retrieve AI classification.|
|GET|/api/v1/admin/audit-events|Search audit events with authorization.|

#### **11.3 External integrations**

|**Integration**|**Purpose**|**Requirement**|
|---|---|---|
|Maps / geocoding|Map rendering, reverse geocoding and optional<br>address search.|Provider abstraction; support OpenStreetMap-<br>compatible options.|
|Object storage|Secure media storage.|S3-compatible API or equivalent; private<br>buckets and signed access.|
|SMS / email / push|OTP, alerts and status notifications.|Provider abstraction and delivery tracking.|
|Speech services|Voice transcription and multilingual input.|Optional provider integration; transcript review.|
|Municipal systems|Future work order or grievance-system<br>exchange.|Documented API, authentication and data<br>mapping; no assumed availability.|
|Analytics / observability|Operational metrics, traces and error<br>monitoring.|Structured logs and metrics with privacy<br>controls.|

### **12. Security, privacy and governance**

#### **12.1 Security requirements**

- Encrypt network traffic using HTTPS/TLS and encrypt sensitive stored data where supported.

- Hash passwords with a modern password hashing algorithm if passwords are used; never store plaintext passwords or OTPs.

- Use short-lived access tokens, refresh-token rotation or secure server sessions, and revocation controls.

- Enforce server-side RBAC and tenant isolation for every read and write operation.

- Validate and sanitize user input; protect against injection, XSS, CSRF and insecure direct object references.

- Validate file type using content inspection, scan uploads where feasible, strip unsafe metadata where appropriate and prevent executable uploads.

- Use private media storage and time-limited signed URLs.

- Require multi-factor authentication for municipal administrators, platform administrators and other privileged staff accounts.

- Apply least-privilege access to service accounts, background workers, AI inference services and infrastructure credentials.

- Make audit events append-only and tamper-evident; restrict who can read or export them.

- Set secure HTTP headers (Content-Security-Policy, HSTS, X-Content-Type-Options), restrictive CORS rules and secure, HttpOnly, SameSite cookies.

- Apply rate limiting, bot/abuse detection and submission throttling.

- Keep secrets in a secrets manager or protected environment configuration; never commit secrets to source control.

- Maintain security logs for authentication, permission changes, data exports and privileged actions.

- Perform dependency scanning, vulnerability remediation and regular backups.

#### **12.2 Privacy requirements**

- Collect only personal information necessary for reporting, communication and operational processing.

- Explain why location permission is requested and provide manual location entry where feasible.

- Do not publicly expose reporter names, phone numbers, email addresses or precise home locations.

- Provide configurable retention and deletion policies subject to legal, audit and public-record obligations.

- Support user requests to access or correct their profile information.

- Define consent and notice for media, location and optional voice data.

- Separate public comments and updates from private administrative notes.

- Apply privacy-preserving aggregation to public hotspot maps.

#### **12.3 Abuse prevention and trust**

- Detect repeated submissions, spam, manipulated images and suspicious verification patterns.

- Use rate limits by account, device, IP or other proportionate signals.

- Provide report flagging and moderation workflows.

- Avoid allowing report volume alone to determine criticality.

- Record manual overrides and moderation decisions for audit.

- Provide appeal or review mechanisms for rejected reports where configured.

### **13. Non-functional requirements**

|**Area**|**Requirement**|
|---|---|
|Performance|Common API reads should target p95 under 500 ms under agreed load,<br>excluding external AI inference and large media transfers. Set production<br>targets after load testing.|
|Submission responsiveness|The user should receive prompt acknowledgement after durable report<br>acceptance; long-running AI processing may continue asynchronously.|
|Availability|Target service availability should be defined per deployment; the platform<br>must degrade gracefully when AI, maps or notification providers fail.|
|Scalability|Support horizontal scaling of stateless API and inference workers; use<br>queues for asynchronous workloads.|
|Reliability|Use retries with backoff, idempotency, transactional writes and dead-<br>letter handling for failed background jobs.|
|Data integrity|Preserve report-to-issue relationships, status history and audit records;<br>enforce referential integrity.|
|Accessibility|Target WCAG 2.2 AA for key citizen and administration workflows where<br>feasible.|
|Localization|Support translated interface strings, locale-aware dates/numbers and<br>Unicode content.|
|Low bandwidth|Compress images, lazy-load map layers, support retryable uploads and<br>avoid requiring large downloads for basic reporting.|
|Compatibility|Support current major mobile and desktop browsers; provide responsive<br>layouts for common low- and mid-range smartphones.|
|Maintainability|Use modular domain boundaries, typed schemas, automated tests,<br>migrations and documented APIs.|
|Observability|Provide structured logs, metrics, tracing, health checks, alerting and<br>correlation IDs.|
|Backup and recovery|Define backup frequency, retention, RPO and RTO for each deployment;<br>test restoration.|
|Portability|Containerize application components and avoid unnecessary provider lock-in for<br>storage, notifications and maps.|

### **14. Analytics and reporting**

#### **14.1 Operational dashboard**

- Total reports submitted, total consolidated issues and reports per issue.

- Open, under-review, assigned, in-progress, overdue, resolved and reopened issue counts.

- Issues by category, severity, priority, department, ward and time period.

- Unique reporters and report volume trends.

- Average and median acknowledgement, assignment and resolution times.

- SLA compliance and overdue workload.

- Duplicate association rate, human-review rate and false-merge feedback.

- Recurring issue locations and hotspot trends.

#### **14.2 Filters and exports**

**AN-001 — Date and geography filters [Must]** Analytics shall support date range, ward, zone, category, priority, status and department filters.

**AN-002 — Export [Must]** Authorized users shall be able to export filtered reports in CSV or spreadsheet-compatible format, subject to data access and privacy controls.

**AN-003 — Scheduled reports [Should]** Administrators should be able to schedule periodic operational summaries for authorized recipients.

**AN-004 — Metric definitions [Must]** Dashboard metrics shall have documented definitions so counts and rates are consistent across views.

### **15. Notifications and communications**

#### **15.1 Notification events**

|**Event**|**Potential recipients**|**Channels**|
|---|---|---|
|Report accepted / reference issued|Citizen|In-app, email or SMS|
|Report linked to an existing issue|Citizen|In-app, push or SMS|
|Status changed|Reporter and followers|In-app, push, email or SMS|
|Issue assigned|Field team / assignee|In-app, push or email|
|Assignment overdue / SLA breach|Supervisor|Dashboard alert, email or push|
|More evidence requested|Citizen|In-app, push or SMS|
|Closure requested|Supervisor and eligible followers|In-app or push|
|Issue reopened|Assigned team and followers|In-app, push or email|

#### **15.2 Notification controls**

- Users shall manage non-essential notification preferences.

- Critical service updates may be delivered according to lawful and configured communication rules.

- Notifications shall not expose sensitive report details on lock screens or shared devices.

- Delivery attempts, failures and provider message identifiers shall be logged.

- Repeated notifications shall be deduplicated or rate-limited.

### **16. Error handling and edge cases**

- Location permission denied: allow manual pin placement or address entry.

- No GPS fix or inaccurate GPS: show accuracy and request confirmation.

- AI service unavailable: accept the report if valid, mark classification pending and route to manual triage.

- Low AI confidence: ask for category selection or send to review.

- Image upload interrupted: allow retry without creating duplicate reports.

- Same report submitted repeatedly: use idempotency and duplicate submission protection.

- Two reports arrive concurrently for the same issue: use transactional association and re-check candidate issues before creating a new issue.

- Two nearby but distinct problems: do not merge based only on distance; require compatible evidence and category.

- Same issue reported after closure: determine whether it is a reopening, recurrence or a new issue using category-specific policy and human review.

- Incorrect AI merge: allow authorized split and preserve all report history.

- Citizen account deleted or anonymized: retain only the minimum records required by applicable policy while preserving issue integrity.

- Out-of-jurisdiction report: route to a configured referral process or explain that the location is unsupported.

- Abusive or misleading content: provide moderation, rejection reason and audit history.

- Map provider outage: retain list-based reporting and issue management.

- Notification provider outage: queue retryable notifications and show in-app status.

- Offline field update conflict: detect stale versions and require reconciliation rather than silently overwriting newer changes.

- Malicious media upload: reject unsupported or unsafe content and record a safe error.

- Public hotspot privacy: aggregate or blur exact locations where needed.

### **17. Acceptance criteria**

|**ID**|**Scenario**|**Expected result**|
|---|---|---|
|AC-01|Citizen submits a valid report with photo and<br>location.|A report reference is returned and the report is<br>visible in the citizen's history.|
|AC-02|AI can classify an image confidently.|Category suggestion and model confidence are<br>stored and displayed.|
|AC-03|AI confidence is low or unavailable.|Report is retained and routed for manual<br>classification.|
|AC-04|A new report matches an existing issue.|The report is linked to the existing issue; report<br>count and distinct reporter count update<br>correctly.|
|AC-05|A nearby report is visually and categorically<br>different.|The system does not auto-merge it; it creates a<br>new issue or sends it for review.|
|AC-06|A match is ambiguous.|A review task shows candidate issues and the<br>matching signals.|
|AC-07|An operator merges two issues.|Reports, history and references are preserved<br>and the merge is audited.|
|AC-08|An operator splits an incorrectly merged issue.|Selected reports move to a separate issue and<br>the operation is audited.|
|AC-09|A critical issue is overdue.|The dashboard shows its priority and SLA<br>breach and configured escalation occurs.|
|AC-10|A supervisor assigns an issue.|The assignee receives a work order and<br>assignment event is recorded.|
|AC-11|A field worker submits completion evidence.|Evidence is stored and issue moves to the<br>configured verification/approval state.|
|AC-12|A citizen reports that the issue remains<br>unresolved.|The issue enters the configured review or<br>reopened state.|
|AC-13|An unauthorized user requests a restricted<br>issue.|The API denies access without disclosing<br>protected information.|
|AC-14|A municipal user queries another tenant's data.|Tenant isolation prevents access.|
|AC-15|A map provider or AI provider is unavailable.|Core reporting and issue management remain<br>usable with graceful degradation.|

### **18. Assumptions, dependencies and open decisions**

#### **18.1 Assumptions**

- The initial deployment will configure one or more municipal jurisdictions and their ward/zone boundaries.

- Citizens can use a modern mobile browser; a native mobile application is not a prerequisite.

- AI models and external service providers may be selected based on evaluation, licensing, cost and deployment constraints.

- Municipal teams will provide or approve the status lifecycle, assignment structure and service-level policies.

- The platform will use synthetic or consented data for demonstrations and testing.

#### **18.2 Dependencies**

- Reliable map tiles and geocoding provider or an alternative map configuration.

- Image classification and embedding model with suitable usage rights.

- Object storage and secure media delivery.

- SMS, email or push provider if those channels are enabled.

- Municipal ward boundaries, service areas and operational team data for a real deployment.

- Legal and privacy review for retention, public visibility, location data and citizen communications.

#### **18.3 Decisions to confirm before production**

- Which municipal jurisdiction and issue categories are enabled at launch?

- Which authentication methods are approved for citizens and municipal staff?

- Are anonymous reports permitted, and what verification restrictions apply?

- Which categories require supervisor approval before closure?

- What are the SLA targets and escalation rules for each priority?

- What location precision is allowed on public maps?

- Which languages are required, and which speech services are acceptable?

- What are media retention periods and applicable public-record obligations?

- Which model licenses and hosting arrangements are acceptable?

- Which municipal systems, if any, will be integrated?

### **Appendix A. Suggested technology architecture**

|**Layer**|**Suggested technology**|**Notes**|
|---|---|---|
|Citizen application|Next.js / React PWA|Responsive reporting, issue tracking,<br>localization and offline-friendly behavior.|
|Administration and field UI|Next.js / React|Role-based work queues, maps, assignment<br>and analytics.|
|API and domain services|Python FastAPI|Modular monolith with clear domain<br>boundaries.|
|Primary database|PostgreSQL|Transactional domain data and audit<br>relationships.|
|Geospatial|PostGIS|Nearby candidate search, jurisdiction<br>boundaries and hotspots.|
|Vector similarity|pgvector|Image and optional text embeddings.|
|Computer vision|Pretrained YOLO or evaluated classifier|Category detection; use only supported classes.|
|Image embeddings|CLIP-family or equivalent evaluated model|Visual similarity; not sole merge criterion.|
|Background processing|Redis + worker queue|Inference, notifications, aggregation and retries.|
|Media storage|S3-compatible object storage|Private buckets, signed URLs and lifecycle<br>policies.|
|Maps|Leaflet + OpenStreetMap-compatible provider|Provider abstraction and attribution.|
|Deployment|Docker; cloud or managed hosting|Scale API and workers independently when<br>required.|
|Observability|Structured logs, metrics and tracing|Health checks, alerts, request correlation and<br>AI quality metrics.|

### **Appendix B. Glossary**

|**Term**|**Meaning**|
|---|---|
|Report|An individual submission made by a citizen or authorized contributor.|
|Civic issue|The consolidated representation of one underlying real-world<br>problem.|
|Duplicate candidate|An existing issue that may represent the same underlying problem as<br>a new report.|
|Deduplication|The process of associating multiple reports with one underlying civic<br>issue when evidence supports it.|
|Hotspot|A geographic area with a concentration or recurrence of civic issues.|
|Priority score|A configurable value used to order work based on severity, impact,<br>age and other factors.|
|SLA|A configured service-level target for acknowledgement, assignment<br>or resolution.|
|Community verification|Citizen feedback on whether a reported issue has actually been<br>resolved.|
|Tenant|A municipal organization or deployment boundary with isolated<br>users, records and configuration.|

##### **End of document**

