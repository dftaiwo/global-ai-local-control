# Participant architecture worksheet — Global AI. Local Control.

**Organisation / use case:** ____________________________________________

## 1. What will your agent do?

- Business process: ____________________________________________
- Required *read* actions: ______________________________________
- Required *write* actions: _____________________________________
- A human must approve: ________________________________________
- Measurable success criterion: _________________________________

## 2. Classify the data

| Information | Public / Internal / Restricted | Where stored | Could the model see it? | Why? |
|---|---|---|---|---|
| Full enterprise records | | | | |
| Names, accounts and identifiers | | | | |
| Aggregate transaction amounts | | | | |
| Opaque record references | | | | |
| User prompts | | | | |
| Tool results | | | | |
| Logs, traces and cached results | | | | |

## 3. Draw the actual trust boundary

- Location of **database**: _____________________________________
- Location of **application / tool gateway**: ____________________
- Model inference **source** Region / service: ____________________
- Model inference **possible destination** Region(s): ____________
- Restricted data allowed to cross? If yes, on what assessed basis? __________
- Where can logs and backups reside? ____________________________

## 4. Enforce controls outside the model

- Identity provider / authenticated role: ________________________
- Approved tool registry: ______________________________________
- Minimum tool argument validation: _____________________________
- Fields permitted in model/tool results: ________________________
- Who signs off high-impact actions? _____________________________
- Audit records that may be retained: ____________________________
- Response to blocked transfer: _________________________________

## 5. Choose the deployment pattern

**A. Regional AWS AI:** remote model processing under approved transfer conditions.

**B. Hybrid local-data AI:** source DB and business rules local, permitted minimal model inputs remote.

**C. Strict local inference:** when protected input must never be processed outside Nigeria, use an approved local model deployment.

Selected pattern: _____ Why? __________________________________

## 6. Your 30-day pilot

| Week | Deliverable | Owner | Acceptance test |
|---|---|---|---|
| 1 | Business use case + data inventory | | |
| 2 | Approved API + architecture / threat model | | |
| 3 | Agent, tool policy, evaluation, audit, approval | | |
| 4 | Pilot + operational measurements + compliance review | | |

## 7. My Monday commitment

On Monday I will add ______________________________________________

to ______________________________________________ (system / workflow)

so that ______________________________________________ cannot happen.

## 8. Production readiness checklist (handout)

The workshop code is a teaching prototype. Before a real deployment, confirm:

- [ ] Identity provider integration, JWT verification and least privilege (no role flags or dropdowns)
- [ ] Data inventory, documented transfer basis and sector-specific legal review
- [ ] Region/SCP/network egress controls and approved model destinations (`aws-check`-style pre-flight in CI)
- [ ] Independent policy engine, DLP and prompt-injection-resistant tools
- [ ] Human approval, idempotency, evaluation and controlled rollback
- [ ] Encrypted storage, logging protection, monitoring and cost controls
- [ ] An audit design that answers the incident-review questions (what can you prove?) without logging raw personal data

**Reminder:** This worksheet supports architecture discovery; it is not a legal determination or proof of Nigerian-only processing.
