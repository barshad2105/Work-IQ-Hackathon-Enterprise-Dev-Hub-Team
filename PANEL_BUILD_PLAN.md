# Work IQ Panel Sections - Multi-Agent Build Plan

## Overview
Build remaining panel sections using a **parallel multi-agent orchestrator** pattern. Each section has a dedicated agent that works independently, with an orchestrator agent that invokes all agents on page load.

---

## Architecture

### Pattern: Orchestrator + Worker Agents
```
Page Load
    ↓
Orchestrator Agent
    ├→ Suggestions Agent
    ├→ Timeline Agent  
    ├→ Next Steps Agent
    └→ [Future agents]
        ↓
    Parallel execution
        ↓
    Results aggregated → Panel sections populated
```

---

## Sections to Build

### 1. 💡 **SUGGESTIONS Section**
**Current State:** Hardcoded 3 items  
**Target State:** Dynamic context-aware suggestions based on conversation + data

**Responsibility:** Generate actionable suggestion chips based on:
- Current conversation topic/context
- Active persona access level
- Available data sources
- Scenario-specific insights

**Agent:** `SuggestionsAgent`
- Input: conversation history, active_persona, available_data_sources
- Output: Array of 4-6 suggestion strings
- API Endpoint: `/api/agent/suggestions`
- Data Storage: Session-based (persists during conversation)

---

### 2. 🕒 **TIMELINE Section**
**Current State:** Empty (placeholder)  
**Target State:** Interactive timeline of conversation, data points, and events

**Responsibility:** Build chronological timeline showing:
- Conversation turn markers with timestamps
- Key entities/events mentioned
- Data source availability windows
- Important action items or decisions

**Agent:** `TimelineAgent`
- Input: conversation history, citations, active_persona
- Output: Array of timeline entries {timestamp, label, type, icon}
- API Endpoint: `/api/agent/timeline`
- Data Storage: Session-based, updates after each message

---

### 3. ✅ **NEXT STEPS Section**
**Current State:** Hardcoded 3 generic steps  
**Target State:** Dynamic context-aware next actions

**Responsibility:** Generate suggested next actions based on:
- Last question/answer
- Unresolved topics
- Incomplete investigations
- Related follow-up areas

**Agent:** `NextStepsAgent`
- Input: last_message, last_response, conversation_context, active_persona
- Output: Array of 3-5 action suggestion objects {label, icon, priority}
- API Endpoint: `/api/agent/nextsteps`
- Data Storage: Session-based, updates after each response

---

### 4. 📊 **PROGRESS Section**
**Current State:** Manual tracking via `assistantResponseCount`  
**Target State:** Rich metrics dashboard

**Responsibility:** Track and display:
- Response count (already tracked)
- Sources accessed (emails, meetings, files, etc.)
- Citation coverage (breadth of data used)
- Persona restrictions status (warnings if limited)
- Session duration / data exploration depth

**Agent:** `ProgressAgent`
- Input: conversation_history, citations_by_source, active_persona
- Output: Progress object {response_count, sources_used, coverage%, depth_score, warnings}
- API Endpoint: `/api/agent/progress`
- Data Storage: Session-based, real-time aggregation

---

## Implementation Details

### Page Load Flow
1. **HTML Loads** → Initial placeholders shown
2. **JavaScript Initialization** → `initPanelOrchestrator()` called
3. **Orchestrator Agent Invoked** → Calls all worker agents in parallel via `/api/agent/orchestrate`
4. **Worker Agents Run** → Each fetches data, computes results
5. **Results Returned** → Aggregated in single response
6. **DOM Updated** → All sections populated simultaneously

### API Endpoints

#### Orchestrator Endpoint
```
POST /api/agent/orchestrate
Request:
{
  "persona": "all",
  "scenario": "c2-contoso",
  "session_data": {...}
}

Response:
{
  "success": true,
  "suggestions": [...],
  "timeline": [...],
  "nextsteps": [...],
  "progress": {...},
  "timestamp": "2026-07-02T23:10:00Z"
}
```

#### Individual Agent Endpoints (for updates after each message)
```
POST /api/agent/suggestions
POST /api/agent/timeline
POST /api/agent/nextsteps
POST /api/agent/progress
```

### JavaScript Integration

#### New Functions
```javascript
// Orchestrator - runs on page load
async function initPanelOrchestrator() {
  const response = await fetch('/api/agent/orchestrate', {...});
  const data = await response.json();
  
  updateSuggestionsPanel(data.suggestions);
  updateTimelinePanel(data.timeline);
  updateNextStepsPanel(data.nextsteps);
  updateProgressPanel(data.progress);
}

// Post-message updates
async function updatePanelAgents() {
  const suggestions = await fetch('/api/agent/suggestions', {...});
  const timeline = await fetch('/api/agent/timeline', {...});
  const nextsteps = await fetch('/api/agent/nextsteps', {...});
  const progress = await fetch('/api/agent/progress', {...});
  
  // Update panels
}
```

---

## Agent Implementation Strategy

### Each Agent Gets:
1. **Separate Python module** in `app.py` or `simulator/agents/`
   - `suggestions_agent.py`
   - `timeline_agent.py`
   - `nextsteps_agent.py`
   - `progress_agent.py`

2. **Independent logic** - No cross-dependencies
   - Read from scenario data
   - Access session state
   - Return JSON response

3. **Mock/Fallback data** - For simulator-only mode
   - Hardcoded suggestions
   - Sample timeline events
   - Default next steps

4. **Parallel execution** - Orchestrator calls all at once
   - Uses asyncio for concurrency
   - Timeout per agent (5s)
   - Graceful degradation if agent fails

---

## Data Sources Available to Agents

**From Scenario:**
- `sc.personas` - Available personas with roles
- `sc.people` - People entities
- `sc.meetings` - Meetings with decisions/action items
- `sc.emails` - Email threads
- `sc.files` - Files and attachments
- `sc.onenote_pages` - OneNote documents
- `sc.tables` - Structured data (action trackers, etc.)

**From Session:**
- `session['persona_id']` - Active persona
- `session['conversation_id']` - Conversation ID
- Conversation history (if stored)
- Previous citations (if cached)

---

## Phased Rollout

### Phase 1: Foundation (This PR)
- [ ] Orchestrator agent stub in `app.py`
- [ ] Individual agent endpoints (return mocked data)
- [ ] JavaScript initialization and panel update functions
- [ ] Page load orchestrator invocation

### Phase 2: Agent Logic (Follow-up)
- [ ] Suggestions agent: context-aware logic
- [ ] Timeline agent: event aggregation
- [ ] Next steps agent: follow-up generation
- [ ] Progress agent: metrics aggregation

### Phase 3: Refinement (Future)
- [ ] Agent learning from user feedback
- [ ] Caching strategy for performance
- [ ] Integration with real LLM (when available)

---

## Testing Strategy

1. **Unit Tests** - Each agent logic
2. **Integration Tests** - Orchestrator calling all agents
3. **E2E Tests** - Page load → panels populated
4. **Performance Tests** - Parallel execution timing

---

## File Structure

```
app.py                          # Add orchestrator + agent endpoints
simulator/agents/
  ├── __init__.py
  ├── orchestrator.py           # Orchestrator logic
  ├── suggestions_agent.py      # Suggestions logic
  ├── timeline_agent.py         # Timeline logic
  ├── nextsteps_agent.py        # Next steps logic
  └── progress_agent.py         # Progress logic

templates/index.html            # Add orchestrator JS function
  ├── initPanelOrchestrator()
  ├── updateSuggestionsPanel()
  ├── updateTimelinePanel()
  └── ... (panel update functions)
```

---

## Benefits of This Approach

✅ **Parallel execution** - All agents run simultaneously  
✅ **Scalable** - Easy to add new agents  
✅ **Fault tolerant** - One agent failure doesn't block others  
✅ **Independent teams** - Each agent can be developed separately  
✅ **Testable** - Clear input/output contracts  
✅ **Future-proof** - Ready for LLM integration  

---

## Questions for Review

1. ✅ Should agents be in separate Python files or in `app.py`?
2. ✅ Any specific data sources agents shouldn't access?
3. ✅ Timeout per agent? (suggested: 3-5 seconds)
4. ✅ Should agents cache results or compute fresh each time?
5. ✅ For timeline - should it include ALL messages or key milestones only?
