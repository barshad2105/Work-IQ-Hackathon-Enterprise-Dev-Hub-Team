/**
 * Orchestrator Functions
 * Panel initialization and update functions for Work IQ interface
 */

// Global ACL state
let currentACL = {
    persona_id: 'all',
    acl: {}
};

async function loadFeatureACL() {
    // Load feature ACL on startup
    try {
        const response = await fetch(`${API_BASE}/api/feature-acl`, {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await parseJsonSafely(response);
        
        if (response.ok && data.success && data.acl) {
            currentACL = {
                persona_id: data.persona_id,
                acl: data.acl
            };
            console.log('[ACL] Loaded feature ACL for persona:', data.persona_id);
            return true;
        }
    } catch (error) {
        console.warn('[ACL] Error loading feature ACL:', error.message);
    }
    
    return false;
}

function hasFeatureAccess(featureName) {
    // Check if current persona has access to a feature
    const featureKey = (featureName || '').toLowerCase().replace(/\s/g, '_').replace(/-/g, '_');
    const hasAccess = currentACL.acl && currentACL.acl[featureKey] === true;
    if (!hasAccess) {
        console.log('[ACL] Access denied for feature:', featureName, '- persona:', currentACL.persona_id);
    }
    return hasAccess;
}

async function initPanelOrchestrator() {
    // Initialize all panel sections on page load.
    try {
        // Load ACL first
        await loadFeatureACL();
        
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
        
        // Load executive brief only if user has access
        if (hasFeatureAccess('executive_brief')) {
            await loadExecutiveBrief();
            // Show the panel
            showFeaturePanel('executive_brief');
        } else {
            // Hide the panel and show access denied message
            hideFeaturePanel('executive_brief');
        }
        
        // Load action recommendations only if user has access
        if (hasFeatureAccess('action_recommendations')) {
            await loadActionRecommendations();
            // Show the panel
            showFeaturePanel('action_recommendations');
        } else {
            // Hide the panel and show access denied message
            hideFeaturePanel('action_recommendations');
        }
        
        // Load scenario timeline only if user has access
        if (hasFeatureAccess('scenario_timeline')) {
            await loadScenarioTimeline();
            showFeaturePanel('scenario_timeline');
        } else {
            hideFeaturePanel('scenario_timeline');
        }
        
        // Load what-if simulation only if user has access
        if (hasFeatureAccess('whatif_simulation')) {
            await loadWhatIfSimulation();
            showFeaturePanel('whatif_simulation');
        } else {
            hideFeaturePanel('whatif_simulation');
        }

        // Load pre-mortem generator only if user has access
        if (hasFeatureAccess('premortem_generator')) {
            await loadPreMortemGenerator();
            showFeaturePanel('premortem_generator');
        } else {
            hideFeaturePanel('premortem_generator');
        }
        
        // Load progress tracking only if user has access
        if (hasFeatureAccess('progress_tracking')) {
            await loadProgressTracking();
            showFeaturePanel('progress_tracking');
        } else {
            hideFeaturePanel('progress_tracking');
        }
        
        // Load interactive dashboard only if user has access
        if (hasFeatureAccess('interactive_dashboard')) {
            await loadInteractiveDashboard();
            showFeaturePanel('interactive_dashboard');
        } else {
            hideFeaturePanel('interactive_dashboard');
        }

        console.log('[ORCHESTRATOR] Panels initialized successfully');
    } catch (error) {
        console.warn('[ORCHESTRATOR] Error initializing panels:', error.message);
    }
}

function showFeaturePanel(featureName) {
    // Show a feature panel by name
    const featurePanelMap = {
        'executive_brief': 'EXECUTIVE BRIEF',
        'action_recommendations': 'ACTION RECOMMENDATIONS',
        'scenario_timeline': 'SCENARIO TIMELINE',
        'whatif_simulation': 'WHAT-IF SIMULATION',
        'premortem_generator': 'PRE-MORTEM GENERATOR',
        'progress_tracking': 'PROGRESS',
        'interactive_dashboard': 'INTERACTIVE DASHBOARD'
    };
    
    const panelTitle = featurePanelMap[featureName];
    if (!panelTitle) return;
    
    const panels = document.querySelectorAll('details');
    for (const panel of panels) {
        if (panel.textContent.includes(panelTitle)) {
            panel.style.display = 'block';
            // Remove any restriction message
            const restrictionMsg = panel.querySelector('.acl-restricted-msg');
            if (restrictionMsg) {
                restrictionMsg.remove();
            }
            console.log('[ACL] Showing feature panel:', featureName);
            break;
        }
    }
}

function hideFeaturePanel(featureName) {
    // Hide a feature panel by name
    const featurePanelMap = {
        'executive_brief': 'EXECUTIVE BRIEF',
        'action_recommendations': 'ACTION RECOMMENDATIONS',
        'scenario_timeline': 'SCENARIO TIMELINE',
        'whatif_simulation': 'WHAT-IF SIMULATION',
        'premortem_generator': 'PRE-MORTEM GENERATOR',
        'progress_tracking': 'PROGRESS',
        'interactive_dashboard': 'INTERACTIVE DASHBOARD'
    };
    
    const panelTitle = featurePanelMap[featureName];
    if (!panelTitle) return;
    
    const panels = document.querySelectorAll('details');
    for (const panel of panels) {
        if (panel.textContent.includes(panelTitle)) {
            panel.style.display = 'none';
            // Add restricted message
            const content = panel.querySelector('.panel-content');
            if (content && !content.querySelector('.acl-restricted-msg')) {
                const msg = document.createElement('div');
                msg.className = 'acl-restricted-msg';
                msg.style.cssText = 'padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; color: #856404; font-size: 12px; margin: 10px 0;';
                msg.textContent = '🔒 Access restricted for your role. Contact administrator for access.';
                content.insertBefore(msg, content.firstChild);
            }
            console.log('[ACL] Hiding feature panel (restricted):', featureName);
            break;
        }
    }
}

function updateFeatureVisibility() {
    // Update visibility of all ACL-controlled features based on current persona
    console.log('[ACL] Updating feature visibility for persona:', currentACL.persona_id);
    
    const features = ['executive_brief', 'action_recommendations', 'scenario_timeline', 'whatif_simulation', 'premortem_generator', 'progress_tracking', 'interactive_dashboard'];
    
    for (const feature of features) {
        if (hasFeatureAccess(feature)) {
            showFeaturePanel(feature);
        } else {
            hideFeaturePanel(feature);
        }
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

async function loadExecutiveBrief() {
    // Fetch and render executive brief with status, risks, blockers, and next actions
    try {
        const briefContent = document.getElementById('executiveBriefContent');
        if (!briefContent) return;

        const response = await fetch(`${API_BASE}/api/agent/executive-brief`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.brief) {
            console.warn('[EXECUTIVE_BRIEF] API unavailable');
            return;
        }

        const brief = data.brief;
        
        // Update health status with color coding
        const healthBadge = document.getElementById('healthBadge');
        if (healthBadge) {
            healthBadge.textContent = brief.overall_health || 'Healthy';
            healthBadge.style.padding = '4px 8px';
            healthBadge.style.borderRadius = '4px';
            healthBadge.style.display = 'inline-block';
            
            if (brief.overall_health === 'Critical') {
                healthBadge.style.backgroundColor = '#ffebee';
                healthBadge.style.color = '#c62828';
            } else if (brief.overall_health === 'At Risk') {
                healthBadge.style.backgroundColor = '#fff3e0';
                healthBadge.style.color = '#e65100';
            } else {
                healthBadge.style.backgroundColor = '#e8f5e9';
                healthBadge.style.color = '#2e7d32';
            }
        }
        
        // Update summary
        const summaryEl = document.getElementById('briefSummary');
        if (summaryEl) {
            summaryEl.textContent = brief.summary || 'No summary available';
        }
        
        // Update risks
        const risksEl = document.getElementById('briefRisks');
        if (risksEl && Array.isArray(brief.risks)) {
            risksEl.innerHTML = brief.risks.map(risk => {
                const levelColor = risk.level === 'high' ? '#c62828' : risk.level === 'medium' ? '#e65100' : '#558b2f';
                return `<li style="margin-bottom: 4px; color: #333;"><span style="color: ${levelColor}; font-weight: 600;">${risk.level.toUpperCase()}</span>: ${escapeHtml(risk.description)}</li>`;
            }).join('');
        }
        
        // Update blockers
        const blockersEl = document.getElementById('briefBlockers');
        if (blockersEl && Array.isArray(brief.blockers)) {
            blockersEl.innerHTML = brief.blockers.map(blocker => {
                const due = blocker.due ? ` (Due: ${blocker.due})` : '';
                const owner = blocker.owner ? ` - Owner: ${blocker.owner}` : '';
                return `<li style="margin-bottom: 4px; color: #333;">${escapeHtml(blocker.description)}${owner}${due}</li>`;
            }).join('');
        }
        
        // Update next actions
        const actionsEl = document.getElementById('briefActions');
        if (actionsEl && Array.isArray(brief.next_actions)) {
            actionsEl.innerHTML = brief.next_actions.map(action => {
                const priorityColor = action.priority === 'high' ? '#c62828' : action.priority === 'medium' ? '#e65100' : '#558b2f';
                const due = action.due ? ` (Due: ${action.due})` : '';
                const owner = action.owner ? ` - Owner: ${action.owner}` : '';
                const priority = action.priority ? ` [${action.priority.toUpperCase()}]` : '';
                return `<li style="margin-bottom: 4px; color: #333;"><span style="color: ${priorityColor}; font-weight: 600;">${priority}</span> ${escapeHtml(action.action)}${owner}${due}</li>`;
            }).join('');
        }
        
        console.log('[EXECUTIVE_BRIEF] Brief loaded successfully');
    } catch (error) {
        console.warn('[EXECUTIVE_BRIEF] Error loading brief:', error.message);
    }
}

async function loadActionRecommendations() {
    // Fetch and render action recommendations with priorities and due dates
    try {
        const contentEl = document.getElementById('actionRecommendationsContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/action-recommendations`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.recommendations) {
            console.warn('[ACTION_RECOMMENDATIONS] API unavailable');
            return;
        }

        const recs = data.recommendations;
        
        // Update summary counts
        document.getElementById('actionsTotalCount').textContent = recs.total_actions || 0;
        document.getElementById('actionsCriticalCount').textContent = recs.critical_count || 0;
        document.getElementById('actionsHighCount').textContent = recs.high_count || 0;
        
        // Update recommendations list
        const listEl = document.getElementById('actionsList');
        if (listEl && Array.isArray(recs.actions)) {
            listEl.innerHTML = recs.actions.map(action => {
                const priorityColor = action.priority === 'critical' ? '#c62828' : 
                                    action.priority === 'high' ? '#d32f2f' : 
                                    action.priority === 'medium' ? '#f57c00' : '#558b2f';
                const priorityBg = action.priority === 'critical' ? '#ffebee' : 
                                 action.priority === 'high' ? '#ffebee' : 
                                 action.priority === 'medium' ? '#fff3e0' : '#f1f8e9';
                
                // Format due date
                let dueDate = 'TBD';
                if (action.due_date) {
                    try {
                        const date = new Date(action.due_date);
                        dueDate = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
                    } catch (e) {
                        dueDate = action.due_date;
                    }
                }
                
                return `
                    <div style="
                        margin-bottom: 8px; 
                        padding: 8px; 
                        background-color: ${priorityBg}; 
                        border-radius: 4px; 
                        border-left: 3px solid ${priorityColor};
                    ">
                        <div style="font-weight: 600; color: #333; margin-bottom: 2px;">
                            ${escapeHtml(action.action)}
                        </div>
                        <div style="color: #666; font-size: 11px; margin-bottom: 4px;">
                            ${escapeHtml(action.description || '')}
                        </div>
                        <div style="display: flex; gap: 12px; font-size: 11px; color: #777;">
                            <span>
                                <strong style="color: ${priorityColor};">${action.priority.toUpperCase()}</strong>
                            </span>
                            <span>Owner: <strong>${escapeHtml(action.owner || 'Unassigned')}</strong></span>
                            <span>Due: <strong>${dueDate}</strong></span>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        console.log('[ACTION_RECOMMENDATIONS] Recommendations loaded successfully');
    } catch (error) {
        console.warn('[ACTION_RECOMMENDATIONS] Error loading recommendations:', error.message);
    }
}

async function loadScenarioTimeline() {
    // Fetch and render scenario timeline with events
    try {
        const contentEl = document.getElementById('timelineContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/scenario-timeline`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.timeline) {
            console.warn('[SCENARIO_TIMELINE] API unavailable, showing demo timeline');
            // Show fallback content
            contentEl.innerHTML = `<div style="padding: 8px; font-size: 12px; color: #666;">
                <div style="color: #999; font-size: 11px; margin-bottom: 8px;">📊 Demo Timeline (API unavailable)</div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                    <div style="padding: 6px; background: #f0f0f0; border-left: 3px solid #4CAF50; border-radius: 2px;">
                        <div style="font-weight: 600; color: #333; font-size: 11px;">14:30 - Issue Detection</div>
                        <div style="color: #666; font-size: 11px;">Alert fired for high memory usage</div>
                    </div>
                    <div style="padding: 6px; background: #f0f0f0; border-left: 3px solid #FFC107; border-radius: 2px;">
                        <div style="font-weight: 600; color: #333; font-size: 11px;">14:45 - Investigation</div>
                        <div style="color: #666; font-size: 11px;">Root cause identified as leak</div>
                    </div>
                    <div style="padding: 6px; background: #f0f0f0; border-left: 3px solid #2196F3; border-radius: 2px;">
                        <div style="font-weight: 600; color: #333; font-size: 11px;">15:00 - Resolution</div>
                        <div style="color: #666; font-size: 11px;">Service restarted successfully</div>
                    </div>
                </div>
            </div>`;
            return;
        }

        const timeline = data.timeline;
        
        // Build timeline HTML
        let html = `<div style="margin-bottom: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px;">
            <strong>${escapeHtml(timeline.scenario_display)}</strong><br>
            <span style="color: #666;">${escapeHtml(timeline.context)}</span><br>
            <span style="color: #999; font-size: 11px;">Total Events: ${timeline.total_events} | Duration: ${timeline.duration}</span>
        </div>`;
        
        if (Array.isArray(timeline.events)) {
            html += '<div style="border-left: 2px solid #2196F3; padding-left: 12px;">';
            for (const event of timeline.events) {
                const severityColor = event.severity === 'critical' ? '#d32f2f' : 
                                     event.severity === 'high' ? '#f57c00' : 
                                     event.severity === 'medium' ? '#fbc02d' : '#558b2f';
                const time = new Date(event.timestamp).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
                html += `
                    <div style="margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #e0e0e0;">
                        <div style="color: ${severityColor}; font-weight: 600; font-size: 11px; margin-bottom: 2px;">
                            ${escapeHtml(event.timestamp.split('T')[1].substring(0, 5))} - ${escapeHtml(event.category)} [${escapeHtml(event.severity).toUpperCase()}]
                        </div>
                        <div style="font-weight: 600; color: #333; margin-bottom: 2px;">${escapeHtml(event.title)}</div>
                        <div style="color: #666; font-size: 11px; margin-bottom: 2px;">${escapeHtml(event.description)}</div>
                        <div style="color: #999; font-size: 10px;">Actor: ${escapeHtml(event.actor)}</div>
                    </div>
                `;
            }
            html += '</div>';
        }
        
        contentEl.innerHTML = html;
        console.log('[SCENARIO_TIMELINE] Timeline loaded successfully');
    } catch (error) {
        console.warn('[SCENARIO_TIMELINE] Error loading timeline:', error.message);
        const contentEl = document.getElementById('timelineContent');
        if (contentEl) {
            contentEl.innerHTML = `<div style="padding: 8px; color: #999; font-size: 11px;">⚠️ Unable to load timeline</div>`;
        }
    }
}

async function loadWhatIfSimulation() {
    // Fetch and render what-if simulation scenarios
    try {
        const contentEl = document.getElementById('whatifContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/whatif-simulation`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.simulation) {
            console.warn('[WHATIF_SIMULATION] API unavailable, showing demo scenarios');
            // Show fallback content
            contentEl.innerHTML = `<div style="font-size: 12px;">
                <div style="margin-bottom: 10px;">
                    <label style="font-weight: 600; display: block; margin-bottom: 6px; color: #333;">Sample Scenarios</label>
                    <div style="padding: 8px; background: #f0f0f0; border-radius: 4px; font-size: 11px; color: #666;">
                        📌 Demo data (APIs offline)
                    </div>
                </div>
                <div style="display: flex; flex-direction: column; gap: 6px;">
                    <div style="padding: 8px; background: #fff3e0; border-left: 3px solid #FFC107; border-radius: 3px;">
                        <div style="font-weight: 600; color: #E65100;">Network Outage</div>
                        <div style="font-size: 11px; color: #666;">Impact: 2-4 day delay</div>
                    </div>
                    <div style="padding: 8px; background: #e3f2fd; border-left: 3px solid #2196F3; border-radius: 3px;">
                        <div style="font-weight: 600; color: #1565C0;">Resource Shortage</div>
                        <div style="font-size: 11px; color: #666;">Impact: 5-7 day delay</div>
                    </div>
                </div>
            </div>`;
            return;
        }

        const sim = data.simulation;
        
        // Build simulation HTML
        let html = `<div style="margin-bottom: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px;">
            <strong>${escapeHtml(sim.scenario_display)}</strong><br>
            <span style="color: #666;">Baseline: ${escapeHtml(sim.baseline_timeline)}</span><br>
            <span style="color: #999; font-size: 11px;">Expected Delay: ~${sim.weighted_risk_delay_days} days</span>
        </div>`;
        
        if (Array.isArray(sim.scenarios)) {
            for (const scenario of sim.scenarios) {
                const riskColor = scenario.risk_level === 'critical' ? '#d32f2f' : 
                                 scenario.risk_level === 'high' ? '#f57c00' : 
                                 scenario.risk_level === 'medium' ? '#fbc02d' : '#558b2f';
                const probPercent = Math.round(scenario.probability * 100);
                html += `
                    <div style="margin-bottom: 10px; padding: 8px; background: #fff; border: 1px solid #ddd; border-left: 3px solid ${riskColor}; border-radius: 3px;">
                        <div style="font-weight: 600; color: #333; margin-bottom: 2px;">${escapeHtml(scenario.name)}</div>
                        <div style="color: #666; font-size: 11px; margin-bottom: 4px;">${escapeHtml(scenario.description)}</div>
                        <div style="display: flex; gap: 12px; font-size: 11px; color: #777;">
                            <span>Probability: <strong>${probPercent}%</strong></span>
                            <span>Impact: <strong>${escapeHtml(scenario.impact)}</strong></span>
                            <span style="color: ${riskColor}; font-weight: 600;">Risk: ${escapeHtml(scenario.risk_level).toUpperCase()}</span>
                        </div>
                    </div>
                `;
            }
        }
        
        html += `<div style="margin-top: 10px; padding: 8px; background: #e3f2fd; border-radius: 3px; font-size: 11px; color: #1565c0;">
            📋 ${escapeHtml(sim.recommendation)}
        </div>`;
        
        contentEl.innerHTML = html;
        console.log('[WHATIF_SIMULATION] Simulation loaded successfully');
    } catch (error) {
        console.warn('[WHATIF_SIMULATION] Error loading simulation:', error.message);
        const contentEl = document.getElementById('whatifContent');
        if (contentEl) {
            contentEl.innerHTML = `<div style="padding: 8px; color: #999; font-size: 11px;">⚠️ Unable to load scenarios</div>`;
        }
    }
}

async function loadPreMortemGenerator() {
    // Fetch and render pre-mortem analysis for active milestone risks
    try {
        const contentEl = document.getElementById('premortemContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/pre-mortem-generator`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const data = await parseJsonSafely(response);
        if (!response.ok || data.__parseError || !data.success || !data.premortem) {
            console.warn('[PREMORTEM_GENERATOR] API unavailable, showing demo risks');
            // Show fallback content
            contentEl.innerHTML = `<div style="font-size: 12px;">
                <div style="margin-bottom: 10px; padding: 8px; background: #fff8e1; border-left: 3px solid #f57c00; border-radius: 3px;">
                    <strong style="color: #5d4037;">Demo Risk Analysis</strong>
                </div>
                <div style="display: flex; flex-direction: column; gap: 6px;">
                    <div style="padding: 6px; background: #ffebee; border-left: 3px solid #c62828; border-radius: 2px;">
                        <div style="font-weight: 600; color: #c62828; font-size: 11px;">Resource Attrition</div>
                        <div style="font-size: 10px; color: #666;">Key team member departure</div>
                    </div>
                    <div style="padding: 6px; background: #f3e5f5; border-left: 3px solid #7b1fa2; border-radius: 2px;">
                        <div style="font-weight: 600; color: #7b1fa2; font-size: 11px;">Technical Debt</div>
                        <div style="font-size: 10px; color: #666;">Accumulated in core modules</div>
                    </div>
                </div>
            </div>`;
            return;
        }

        const pm = data.premortem;

        let html = `<div style="margin-bottom: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px;">
            <strong>${escapeHtml(pm.scenario_display || 'Scenario')}</strong><br>
            <span style="color: #666;">Milestone: ${escapeHtml(pm.active_milestone || 'N/A')}</span><br>
            <span style="color: #666;">Target: ${escapeHtml(pm.target_date || 'N/A')}</span><br>
            <span style="color: #999; font-size: 11px;">Risk score: ${escapeHtml(String(pm.risk_score || 0))} | Window: ${escapeHtml(String(pm.risk_window_days || 0))} days</span>
        </div>`;

        html += `<div style="margin-bottom: 10px; padding: 8px; background: #fff8e1; border-left: 3px solid #f57c00; border-radius: 3px; font-size: 11px; color: #5d4037;">
            <strong>Highest Risk Mode:</strong> ${escapeHtml(pm.highest_risk_mode || 'N/A')}
        </div>`;

        if (Array.isArray(pm.failure_modes) && pm.failure_modes.length > 0) {
            html += '<div style="font-size: 12px; font-weight: 600; margin-bottom: 6px; color: #333;">Likely Failure Paths</div>';
            for (const mode of pm.failure_modes) {
                const impactColor = mode.impact === 'critical' ? '#d32f2f' : mode.impact === 'high' ? '#ef6c00' : mode.impact === 'medium' ? '#f9a825' : '#558b2f';
                const probPct = Math.round((Number(mode.probability) || 0) * 100);
                html += `
                    <div style="margin-bottom: 8px; padding: 8px; background: #fff; border: 1px solid #ddd; border-left: 3px solid ${impactColor}; border-radius: 3px;">
                        <div style="font-weight: 600; color: #333; margin-bottom: 2px;">${escapeHtml(mode.name || 'Risk')}</div>
                        <div style="font-size: 11px; color: #666; margin-bottom: 4px;">Signal: ${escapeHtml(mode.early_signal || 'N/A')}</div>
                        <div style="display: flex; gap: 12px; font-size: 11px; color: #777;">
                            <span>Probability: <strong>${probPct}%</strong></span>
                            <span>Impact: <strong style="color:${impactColor};">${escapeHtml(String(mode.impact || '').toUpperCase())}</strong></span>
                        </div>
                        <div style="font-size: 11px; color: #777; margin-top: 3px;">Blast radius: ${escapeHtml(mode.blast_radius || '')}</div>
                    </div>
                `;
            }
        }

        if (Array.isArray(pm.preventive_actions) && pm.preventive_actions.length > 0) {
            html += '<div style="font-size: 12px; font-weight: 600; margin: 10px 0 6px; color: #333;">Preventive Actions</div>';
            html += pm.preventive_actions.map(action => {
                const priorityColor = action.priority === 'high' ? '#c62828' : action.priority === 'medium' ? '#ef6c00' : '#2e7d32';
                return `
                    <div style="margin-bottom: 6px; padding: 6px; background: #f9f9f9; border-radius: 3px; font-size: 11px;">
                        <div style="font-weight: 600; color: #333;">${escapeHtml(action.action || '')}</div>
                        <div style="display:flex; gap:10px; color:#666; margin-top: 2px;">
                            <span>Owner: <strong>${escapeHtml(action.owner || 'Unassigned')}</strong></span>
                            <span>Due: <strong>${escapeHtml(action.due || 'TBD')}</strong></span>
                            <span style="color:${priorityColor}; font-weight: 600;">${escapeHtml(String(action.priority || '').toUpperCase())}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }

        html += `<div style="margin-top: 10px; padding: 8px; background: #e8f5e9; border-radius: 3px; font-size: 11px; color: #2e7d32;">
            ✅ ${escapeHtml(pm.recommendation || '')}
        </div>`;

        contentEl.innerHTML = html;
        console.log('[PREMORTEM_GENERATOR] Pre-mortem loaded successfully');
    } catch (error) {
        console.warn('[PREMORTEM_GENERATOR] Error loading pre-mortem:', error.message);
        const contentEl = document.getElementById('premortemContent');
        if (contentEl) {
            contentEl.innerHTML = `<div style="padding: 8px; color: #999; font-size: 11px;">⚠️ Unable to load risk analysis</div>`;
        }
    }
}

async function loadProgressTracking() {
    // Fetch and render progress tracking with 7-day trend
    try {
        const contentEl = document.getElementById('progressContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/progress-tracking`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.progress) {
            console.warn('[PROGRESS_TRACKING] API unavailable, showing demo progress');
            // Show fallback content
            contentEl.innerHTML = `<div style="font-size: 12px;">
                <div style="margin-bottom: 10px; padding: 8px; background: #e8f5e9; border-left: 3px solid #4caf50; border-radius: 3px;">
                    <div style="font-size: 11px; color: #2e7d32;">
                        <strong>Trend: UPWARD +8%</strong>
                    </div>
                </div>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    <div style="padding: 4px; background: #f9f9f9; border-radius: 2px; font-size: 11px; color: #666;">✓ System availability improved</div>
                    <div style="padding: 4px; background: #f9f9f9; border-radius: 2px; font-size: 11px; color: #666;">✓ Response time optimized</div>
                    <div style="padding: 4px; background: #f9f9f9; border-radius: 2px; font-size: 11px; color: #666;">✓ Error rate reduced</div>
                </div>
            </div>`;
            return;
        }

        const progress = data.progress;
        
        // Build progress HTML
        let html = `<div style="margin-bottom: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 12px;">
            <strong>${escapeHtml(progress.scenario_display)}</strong><br>
            <span style="color: #666;">Trend: <strong>${progress.trend_direction.toUpperCase()}</strong> ${progress.trend_percentage > 0 ? '+' : ''}${progress.trend_percentage}%</span><br>
            <span style="color: #999; font-size: 11px;">Current: ${progress.current_value}% | Incidents: ${progress.total_incidents}</span>
        </div>`;
        
        // Data points summary
        html += `<div style="margin-bottom: 10px; padding: 8px; background: #e8f5e9; border-radius: 3px; border-left: 3px solid #4caf50;">
            <div style="font-size: 11px; color: #2e7d32;">
                <strong>7-Day Activity:</strong> 
                ${progress.improving_days} Improving | 
                ${progress.declining_days} Declining | 
                ${progress.flat_days} Stable
            </div>
        </div>`;
        
        // Recent activities
        if (Array.isArray(progress.activities)) {
            html += '<div style="font-size: 12px; font-weight: 600; margin-bottom: 6px; color: #333;">Recent Activities:</div>';
            html += progress.activities.map(act => 
                `<div style="margin-bottom: 4px; padding: 4px; background: #f9f9f9; border-radius: 2px; font-size: 11px; color: #666;">✓ ${escapeHtml(act)}</div>`
            ).join('');
        }
        
        html += `<div style="margin-top: 10px; padding: 8px; background: #f0f0f0; border-radius: 3px; font-size: 11px; color: #555;">
            📊 ${escapeHtml(progress.summary)}
        </div>`;
        
        contentEl.innerHTML = html;
        console.log('[PROGRESS_TRACKING] Progress tracking loaded successfully');
    } catch (error) {
        console.warn('[PROGRESS_TRACKING] Error loading progress tracking:', error.message);
        const contentEl = document.getElementById('progressContent');
        if (contentEl) {
            contentEl.innerHTML = `<div style="padding: 8px; color: #999; font-size: 11px;">⚠️ Unable to load progress data</div>`;
        }
    }
}

async function loadInteractiveDashboard() {
    // Fetch and render interactive dashboard with KPIs
    try {
        const contentEl = document.getElementById('dashboardContent');
        if (!contentEl) return;

        const response = await fetch(`${API_BASE}/api/agent/interactive-dashboard`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        let data = await parseJsonSafely(response);
        
        if (!response.ok || data.__parseError || !data.success || !data.dashboard) {
            console.warn('[INTERACTIVE_DASHBOARD] API unavailable, showing demo dashboard');
            // Show fallback content
            contentEl.innerHTML = `<div style="font-size: 12px;">
                <div style="margin-bottom: 10px;">
                    <span style="display: inline-block; padding: 4px 8px; background-color: #4caf5020; border: 1px solid #4caf50; border-radius: 3px; color: #4caf50; font-weight: 600; font-size: 11px;">
                        ● Healthy
                    </span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
                    <div style="padding: 6px; background: #f0f7ff; border-radius: 3px; border-left: 3px solid #2196F3;">
                        <div style="font-size: 11px; color: #666;">Total Items</div>
                        <div style="font-size: 14px; font-weight: 700; color: #1976D2;">248</div>
                    </div>
                    <div style="padding: 6px; background: #fff3e0; border-radius: 3px; border-left: 3px solid #FF9800;">
                        <div style="font-size: 11px; color: #666;">Open Issues</div>
                        <div style="font-size: 14px; font-weight: 700; color: #F57C00;">12</div>
                    </div>
                </div>
                <div style="padding: 6px; background: #f9f9f9; border-radius: 2px; font-size: 10px; color: #666;">
                    📊 Demo data (APIs offline)
                </div>
            </div>`;
            return;
        }

        const dashboard = data.dashboard;
        
        // Health status color
        const healthColor = dashboard.health_color === 'red' ? '#d32f2f' : 
                           dashboard.health_color === 'yellow' ? '#f57c00' : '#4caf50';
        
        // Build dashboard HTML
        let html = `<div style="margin-bottom: 12px; padding: 8px; background: #f5f5f5; border-radius: 4px;">
            <div style="font-size: 12px; font-weight: 600; color: #333; margin-bottom: 4px;">
                ${escapeHtml(dashboard.scenario_display)}
            </div>
            <div style="display: inline-block; padding: 4px 8px; background-color: ${healthColor}20; border: 1px solid ${healthColor}; border-radius: 3px; color: ${healthColor}; font-weight: 600; font-size: 12px;">
                ● ${escapeHtml(dashboard.health_status)}
            </div>
        </div>`;
        
        // KPIs
        if (Array.isArray(dashboard.kpis)) {
            html += '<div style="margin-bottom: 10px;">';
            for (const kpi of dashboard.kpis) {
                const kpiColor = kpi.status === 'critical' ? '#d32f2f' : 
                                kpi.status === 'warning' ? '#f57c00' : '#4caf50';
                html += `
                    <div style="margin-bottom: 6px; padding: 6px; background: #f9f9f9; border-radius: 2px; font-size: 11px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="color: #333; font-weight: 600;">${escapeHtml(kpi.label)}</span>
                            <span style="color: ${kpiColor}; font-weight: 600; font-size: 12px;">${escapeHtml(kpi.value)}</span>
                        </div>
                        <div style="color: #999; font-size: 10px;">Target: ${escapeHtml(kpi.target)}</div>
                    </div>
                `;
            }
            html += '</div>';
        }
        
        // Blockers
        if (dashboard.blocker_count > 0 && Array.isArray(dashboard.top_blockers)) {
            html += '<div style="margin-bottom: 10px;">';
            html += `<div style="font-size: 11px; font-weight: 600; color: #d32f2f; margin-bottom: 4px;">🔴 ${dashboard.blocker_count} Active Blocker(s)</div>`;
            for (const blocker of dashboard.top_blockers.slice(0, 3)) {
                const sevColor = blocker.severity === 'high' ? '#d32f2f' : '#f57c00';
                html += `
                    <div style="margin-bottom: 4px; padding: 4px; background: #ffebee; border-left: 2px solid ${sevColor}; border-radius: 2px; font-size: 10px;">
                        <div style="color: #333; font-weight: 600;">${escapeHtml(blocker.title)}</div>
                        <div style="color: #666; font-size: 9px;">Owner: ${escapeHtml(blocker.owner)} (${blocker.age_days}d)</div>
                    </div>
                `;
            }
            html += '</div>';
        }
        
        // Top actions
        if (dashboard.action_count > 0 && Array.isArray(dashboard.top_actions)) {
            html += '<div>';
            html += `<div style="font-size: 11px; font-weight: 600; color: #4caf50; margin-bottom: 4px;">✅ ${dashboard.action_count} Action(s) (${dashboard.critical_action_count} Critical)</div>`;
            for (const action of dashboard.top_actions.slice(0, 3)) {
                const actColor = action.priority === 'critical' ? '#d32f2f' : action.priority === 'high' ? '#f57c00' : '#558b2f';
                html += `
                    <div style="margin-bottom: 4px; padding: 4px; background: #f1f8e9; border-left: 2px solid ${actColor}; border-radius: 2px; font-size: 10px;">
                        <div style="color: #333; font-weight: 600;">${escapeHtml(action.action)}</div>
                        <div style="color: #666; font-size: 9px;">Owner: ${escapeHtml(action.owner)} | Due: ${escapeHtml(action.due)}</div>
                    </div>
                `;
            }
            html += '</div>';
        }
        
        contentEl.innerHTML = html;
        console.log('[INTERACTIVE_DASHBOARD] Dashboard loaded successfully');
    } catch (error) {
        console.warn('[INTERACTIVE_DASHBOARD] Error loading dashboard:', error.message);
        const contentEl = document.getElementById('dashboardContent');
        if (contentEl) {
            contentEl.innerHTML = `<div style="padding: 8px; color: #999; font-size: 11px;">⚠️ Unable to load dashboard</div>`;
        }
    }
}
