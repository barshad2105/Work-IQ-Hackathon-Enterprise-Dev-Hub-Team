"""
Suggestions Agent - Generates context-aware suggestion chips for the SUGGESTIONS panel.
"""

import json


class SuggestionsAgent:
    """Generates actionable suggestion chips based on conversation context."""

    @staticmethod
    def generate(scenario, persona_id: str = None, conversation_history: list = None) -> list:
        """
        Generate suggestions based on scenario data and current context.
        
        Args:
            scenario: Loaded scenario object
            persona_id: Active persona ID
            conversation_history: List of previous messages
            
        Returns:
            List of suggestion strings (4-6 items)
        """
        suggestions = []

        # Scenario-specific suggestions
        try:
            # Load scenario metadata if available
            if hasattr(scenario, 'metadata'):
                meta = scenario.metadata
                if meta and isinstance(meta, dict):
                    if 'suggested_queries' in meta:
                        suggestions.extend(meta['suggested_queries'][:3])
        except Exception:
            pass

        # Default suggestions based on scenario
        scenario_name = getattr(scenario, 'name', 'unknown')

        # Map scenarios to relevant suggestions
        scenario_suggestions = {
            'c1-northbridge': [
                'What are the pending CAPA items?',
                'Show capacity planning status',
                'List open improvement actions',
            ],
            'c2-contoso': [
                'What is blocking qualification?',
                'Who owns PPAP plan?',
                'Show OneNote recovery log summary',
            ],
            'c3-meridian': [
                'What are active engagements?',
                'Show project milestone status',
                'List resource allocation issues',
            ],
            'c4-arundel': [
                'What maintenance work is pending?',
                'Show work order priority list',
                'List critical CMMS items',
            ],
            'c5-westbrook': [
                'What accreditation items remain?',
                'Show AOL status by department',
                'List overdue compliance items',
            ],
            'c6-edkh': [
                'What are open action items?',
                'Show on-call escalations',
                'List pending owner reviews',
            ],
        }

        # Add scenario-specific suggestions
        default_suggestions = scenario_suggestions.get(scenario_name, [
            'What is the current status?',
            'Show key action items',
            'List recent decisions',
        ])

        # If no suggestions yet, use defaults
        if not suggestions:
            suggestions = default_suggestions[:6]

        # Filter by persona access if needed (optional)
        if persona_id and persona_id != 'all':
            persona = scenario.get_persona(persona_id)
            if persona and isinstance(persona, dict):
                access_level = persona.get('access_level', 'standard')
                # Could restrict suggestions based on access level here

        # Ensure we have 4-6 suggestions
        if len(suggestions) < 4:
            suggestions.extend([
                'Show summary',
                'List key people',
            ])

        return suggestions[:6]
