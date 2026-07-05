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
        
        // Load progress trend
        await loadProgressTrend();

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

async function loadProgressTrend() {
    // Fetch and render 7-day trend data for PROGRESS panel
    try {
        const trendCanvas = document.getElementById('trendChart');
        const trendLabel = document.getElementById('trendLabel');
        if (!trendCanvas || !trendLabel) return;

        const response = await fetch(`${API_BASE}/api/agent/progress-trend`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        // Fallback to demo data if API is unavailable
        if (!response.ok || data.__parseError || !data.success || !data.trend) {
            console.warn('[PROGRESS] API unavailable, using demo trend data');
            data = {
                success: true,
                trend: [2, 3, 2, 4, 5, 6, 7],  // Sample: Shows improving trend
                trendDirection: 'improving',
                trendDescription: '↑ Activity improving - More emails & meetings'
            };
        }

        renderTrendChart(trendCanvas, data.trend, data.trendDirection);
        trendLabel.textContent = data.trendDescription || 'Trend over last 7 days';
    } catch (error) {
        console.warn('[PROGRESS] Error loading trend:', error.message);
        // Render demo data on error
        const trendCanvas = document.getElementById('trendChart');
        const trendLabel = document.getElementById('trendLabel');
        if (trendCanvas && trendLabel) {
            renderTrendChart(trendCanvas, [2, 3, 2, 4, 5, 6, 7], 'improving');
            trendLabel.textContent = '↑ Activity improving - Demo data shown';
        }
    }
}

function renderTrendChart(canvas, trendData, direction) {
    // Render trend line chart on canvas
    if (!canvas || !Array.isArray(trendData) || trendData.length < 2) {
        return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.clientWidth || 300;
    const height = canvas.clientHeight || 80;
    
    canvas.width = width * (window.devicePixelRatio || 1);
    canvas.height = height * (window.devicePixelRatio || 1);
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    const padding = 10;
    const graphWidth = width - 2 * padding;
    const graphHeight = height - 2 * padding;

    // Determine color based on trend direction
    let lineColor = '#999999'; // Grey (neutral)
    if (direction === 'improving') lineColor = '#4CAF50'; // Green
    else if (direction === 'declining') lineColor = '#F44336'; // Red

    // Normalize data to fit canvas
    const maxVal = Math.max(...trendData, 1);
    const minVal = Math.min(...trendData, 0);
    const range = maxVal - minVal || 1;

    // Draw background
    ctx.fillStyle = '#f9f9f9';
    ctx.fillRect(padding, padding, graphWidth, graphHeight);

    // Draw grid lines
    ctx.strokeStyle = '#e0e0e0';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padding + (graphHeight / 4) * i;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(padding + graphWidth, y);
        ctx.stroke();
    }

    // Draw trend line
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();

    for (let i = 0; i < trendData.length; i++) {
        const x = padding + (graphWidth / (trendData.length - 1)) * i;
        const normalizedVal = (trendData[i] - minVal) / range;
        const y = padding + graphHeight - normalizedVal * graphHeight;

        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    }
    ctx.stroke();

    // Draw data points
    ctx.fillStyle = lineColor;
    for (let i = 0; i < trendData.length; i++) {
        const x = padding + (graphWidth / (trendData.length - 1)) * i;
        const normalizedVal = (trendData[i] - minVal) / range;
        const y = padding + graphHeight - normalizedVal * graphHeight;

        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    }
}

