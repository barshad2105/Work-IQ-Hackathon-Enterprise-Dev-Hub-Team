"""
Next Steps Agent - Generates follow-up action suggestions for the NEXT STEPS panel.
"""

import json


class NextStepsAgent:
    """Generates context-aware next step suggestions."""

    @staticmethod
    def generate(scenario, persona_id: str = None, last_response: str = None, conversation_history: list = None) -> list:
        """
        Generate next step suggestions based on context.
        
        Args:
            scenario: Loaded scenario object
            persona_id: Active persona ID
            last_response: Last assistant response text
            conversation_history: List of messages
            
        Returns:
            List of action objects {label, icon, priority}
        """
        next_steps = []

        # Analyze last response for action items if provided
        if last_response and isinstance(last_response, str):
            response_lower = last_response.lower()
            
            # Look for common action indicators
            if 'action' in response_lower or 'todo' in response_lower:
                next_steps.append({
                    'label': 'Review open actions',
                    'icon': '✓',
                    'priority': 'high',
                })
            
            if 'owner' in response_lower or 'assign' in response_lower:
                next_steps.append({
                    'label': 'Verify ownership',
                    'icon': '👤',
                    'priority': 'high',
                })
            
            if 'timeline' in response_lower or 'date' in response_lower or 'deadline' in response_lower:
                next_steps.append({
                    'label': 'Check deadlines',
                    'icon': '⏰',
                    'priority': 'high',
                })

        # Add scenario-specific next steps
        scenario_name = getattr(scenario, 'name', 'unknown')
        scenario_steps = {
            'c1-northbridge': [
                {'label': 'Review CAPA metrics', 'icon': '📊', 'priority': 'medium'},
                {'label': 'Schedule follow-up', 'icon': '📅', 'priority': 'medium'},
            ],
            'c2-contoso': [
                {'label': 'Update qualification status', 'icon': '✓', 'priority': 'high'},
                {'label': 'Notify stakeholders', 'icon': '🔔', 'priority': 'medium'},
            ],
            'c3-meridian': [
                {'label': 'Review engagement updates', 'icon': '📈', 'priority': 'medium'},
                {'label': 'Confirm resource allocation', 'icon': '👥', 'priority': 'high'},
            ],
            'c4-arundel': [
                {'label': 'Process work orders', 'icon': '🔧', 'priority': 'high'},
                {'label': 'Update maintenance log', 'icon': '📝', 'priority': 'medium'},
            ],
            'c5-westbrook': [
                {'label': 'Complete accreditation tasks', 'icon': '✅', 'priority': 'high'},
                {'label': 'Review compliance items', 'icon': '⚖️', 'priority': 'high'},
            ],
            'c6-edkh': [
                {'label': 'Resolve open actions', 'icon': '🎯', 'priority': 'high'},
                {'label': 'Update on-call status', 'icon': '📱', 'priority': 'high'},
            ],
        }

        # Add scenario-specific suggestions if we haven't reached 3+ steps
        if len(next_steps) < 3:
            default_steps = scenario_steps.get(scenario_name, [
                {'label': 'Draft response', 'icon': '✍️', 'priority': 'medium'},
                {'label': 'Set reminder', 'icon': '⏰', 'priority': 'low'},
                {'label': 'Review sources', 'icon': '📚', 'priority': 'medium'},
            ])
            next_steps.extend(default_steps)

        # Limit to 5 steps
        return next_steps[:5]
