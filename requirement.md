# Work IQ Hackathon Requirements

## Objective
Create a high-impact Work IQ demonstration for hackathon judging with clear business value, explainable outputs, and actionable outcomes.

## Backlog (Prioritized by Impact Weightage)
Move items from this section to "Active Development List" as implementation starts.

| Rank | Feature | Impact (1-10) | Why It Matters for Hackathon |
|---|---|---:|---|
| 1 | Cross-app Single Answer Copilot (Email + Teams + Files + Notes + Tables) | 10.0 | Strongest Work IQ story: one trusted answer from fragmented enterprise context. |
| 2 | Decision-Ready Executive Briefs (status, risks, blockers, next actions) | 9.7 | Immediate business value and leadership-facing outcomes. |
| 3 | Risk/Delay Early Warning with confidence indicators | 9.4 | Demonstrates proactive intelligence, not just reactive search. |
| 4 | Natural language query to structured insights | 9.2 | Shows intuitive UX and reasoning across mixed data types. |
| 5 | Persona-aware responses (PM vs Executive vs Engineer) | 8.9 | Highlights context personalization and relevance. |
| 6 | Action recommendation engine (owner + due date suggestions) | 8.7 | Converts insights into execution-ready recommendations. |
| 7 | Source traceability and explainability (citations) | 8.5 | Builds trust with verifiable evidence from source artifacts. |
| 8 | Scenario playback / incident timeline reconstruction | 8.3 | Excellent storytelling mechanism for live demos. |
| 9 | Meeting intelligence (minutes, decisions, owners, follow-ups) | 8.1 | Universally relatable productivity value. |
| 10 | Cross-scenario benchmarking and prioritization | 7.8 | Shows portfolio-level intelligence and comparative reasoning. |
| 11 | What-if simulation for milestone impact | 7.6 | Adds advanced planning and decision-support capability. |
| 12 | Policy/compliance guardrails in responses | 7.3 | Improves enterprise readiness and responsible AI posture. |
| 13 | Role-based data access-aware responses | 7.1 | Demonstrates secure, audience-appropriate answer shaping. |
| 14 | Automated worklog/status mail drafting | 6.8 | Practical time-saver for day-to-day teams. |
| 15 | Interactive dashboard snapshot (health, blockers, actions) | 6.5 | Good visual support when paired with strong AI reasoning. |

## Active Development List
Manually move selected features here when development starts.

### Active Item Template
Copy this block for each feature moved from backlog.

Feature:
Owner:
Status: Planned | In Progress | Blocked | Demo Ready | Done
ETA:
Demo Prompt:
Expected Output:
Dependencies:
Notes:

### Active Items Tracker
| Feature | Owner | Status | ETA | Demo Prompt |
|---|---|---|---|---|
| (Add first feature from backlog) | (Name) | Planned | (YYYY-MM-DD) | (Prompt to run in demo) |

## Development Topics (Pick and Plan)
Use this section to choose implementation tracks and define scope.

### 1) Data and Context Layer
- [ ] Multi-source ingestion contract (emails, meetings, files, notes, tables)
- [ ] Unified context schema and entity normalization
- [ ] Scenario-specific adapters and test fixtures
- [ ] Data freshness and retrieval strategy

### 2) Intelligence and Reasoning Layer
- [ ] Prompt orchestration for synthesis and summarization
- [ ] Risk scoring heuristic and confidence scoring
- [ ] Persona-aware response shaping logic
- [ ] Action recommendation generation and ranking

### 3) Trust, Safety, and Governance
- [ ] Source citation formatting and traceability rules
- [ ] Hallucination containment patterns (grounded answer requirements)
- [ ] Compliance guardrails and safe-answer policy checks
- [ ] Role-based visibility filters

### 4) Product and UX Demonstration
- [ ] Demo flow design (7-minute and 12-minute variants)
- [ ] Narrative states: question -> insight -> evidence -> action
- [ ] Output templates (executive brief, risk report, meeting digest)
- [ ] Fail-safe demo fallback responses

### 5) Engineering and Delivery
- [ ] API contracts and endpoint design
- [ ] Evaluation harness updates (quality, grounding, usefulness)
- [ ] Automated test coverage for high-impact scenarios
- [ ] Performance and latency budget for live demo

### 6) Hackathon Readiness
- [ ] Judge-facing value proposition (problem, differentiation, ROI)
- [ ] Demo script with expected outputs per step
- [ ] Backup scenarios if primary scenario fails
- [ ] Final checklist: reliability, clarity, and reproducibility

## Notes
- Keep backlog priority order stable unless scoring criteria change.
- If needed, add columns for effort, risk, and owner to improve sprint planning.
