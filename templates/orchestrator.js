/**
 * Orchestrator Functions
 * Panel initialization and update functions for Work IQ interface
 */

async function initPanelOrchestrator() {
    // Initialize all panel sections on page load.
    try {
        const response = await fetch(`${API_BASE}/api/agent/orchestrate`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const data = await parseJsonSafely(response);

        if (!response.ok || data.__parseError || !data.success) {
            console.warn('[ORCHESTRATOR] Failed to initialize panels:', data.error);
            return;
        }

        // Update all panels with results
        if (data.timeline) updateTimelinePanel(data.timeline);
        if (data.nextsteps) updateNextStepsPanel(data.nextsteps);

        console.log('[ORCHESTRATOR] Panels initialized successfully');
    } catch (error) {
        console.warn('[ORCHESTRATOR] Error initializing panels:', error.message);
    }
}

function updateTimelinePanel(timelineEntries) {
    // Update TIMELINE panel with events.
    if (!Array.isArray(timelineEntries) || timelineEntries.length === 0) {
        return;
    }

    const sourceTags = document.getElementById('sourceTags');
    if (!sourceTags) return;

    sourceTags.innerHTML = timelineEntries
        .slice(0, 6)
        .map((entry) => {
            const icon = entry.icon || '•';
            const label = entry.label || entry.timestamp || '';
            return `<span class="source-tag" title="${escapeHtml(label)}">${icon} ${escapeHtml(label.slice(0, 30))}</span>`;
        })
        .join('');
}

function updateNextStepsPanel(nextsteps) {
    // Update NEXT STEPS panel with actions.
    if (!Array.isArray(nextsteps) || nextsteps.length === 0) {
        return;
    }

    // Find the NEXT STEPS panel content
    const panels = document.querySelectorAll('details');
    let nextStepsContent = null;

    for (const panel of panels) {
        if (panel.textContent.includes('NEXT STEPS')) {
            nextStepsContent = panel.querySelector('.panel-content');
            break;
        }
    }

    if (!nextStepsContent) return;

    const stepActionsDiv = nextStepsContent.querySelector('.step-actions') || nextStepsContent;
    stepActionsDiv.innerHTML = nextsteps
        .map((step) => {
            const icon = step.icon || '→';
            const label = step.label || '';
            const priority = step.priority || 'medium';
            return `<span class="chip" data-priority="${priority}" title="${priority} priority">${icon} ${escapeHtml(label)}</span>`;
        })
        .join('');
}

async function updateAllPanelsAfterMessage(response) {
    // Update all panels after a message is processed.
    try {
        const updateBody = {
            last_response: response || '',
            conversation_history: [],
            citations: [],
            response_count: assistantResponseCount
        };

        // Call individual agents for updates (can also call orchestrate)
        const [timelineRes, nextstepsRes] = await Promise.all([
            fetch(`${API_BASE}/api/agent/timeline`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updateBody)
            }),
            fetch(`${API_BASE}/api/agent/nextsteps`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updateBody)
            })
        ]);

        if (timelineRes.ok) {
            const data = await parseJsonSafely(timelineRes);
            if (data.success && data.timeline) {
                updateTimelinePanel(data.timeline);
            }
        }

        if (nextstepsRes.ok) {
            const data = await parseJsonSafely(nextstepsRes);
            if (data.success && data.nextsteps) {
                updateNextStepsPanel(data.nextsteps);
            }
        }
    } catch (error) {
        console.warn('[PANELS] Error updating panels after message:', error.message);
    }
}
