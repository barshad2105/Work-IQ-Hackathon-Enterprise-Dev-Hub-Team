"""
Progress Agent - Aggregates session metrics for the PROGRESS panel.
"""

from collections import defaultdict


class ProgressAgent:
    """Aggregates and tracks session progress metrics."""

    @staticmethod
    def generate(scenario, persona_id: str = None, response_count: int = 0, citations: list = None, conversation_history: list = None) -> dict:
        """
        Generate progress metrics based on session data.
        
        Args:
            scenario: Loaded scenario object
            persona_id: Active persona ID
            response_count: Number of assistant responses
            citations: List of citations used across all responses
            conversation_history: List of all messages
            
        Returns:
            Progress object {response_count, sources_used, coverage%, depth_score, warnings}
        """
        
        # Count responses
        responses = response_count or 0

        # Extract sources from citations
        sources_used = defaultdict(int)
        if citations and isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict):
                    kind = citation.get('kind', 'unknown')
                    sources_used[kind] += 1

        # Map kinds to source categories
        kind_to_source = {
            'email': 'Emails',
            'meeting': 'Meetings',
            'teams_message': 'Teams',
            'file': 'Files',
            'onenote_page': 'OneNote',
            'milestone': 'Tables',
            'capa': 'Tables',
            'action_item': 'Meetings',
            'person': 'People',
        }

        source_categories = set()
        for kind in sources_used.keys():
            source = kind_to_source.get(kind)
            if source:
                source_categories.add(source)

        # Calculate coverage percentage
        total_available_sources = 6  # emails, meetings, teams, files, onenote, tables
        coverage_percent = min(100, int((len(source_categories) / total_available_sources) * 100))

        # Calculate depth score (0-10) based on responses and breadth
        depth_score = min(10, (responses * 2) + len(source_categories))

        # Check persona restrictions
        warnings = []
        if persona_id and persona_id != 'all':
            persona = scenario.get_persona(persona_id)
            if persona:
                access_level = persona.get('access_level', 'standard')
                if access_level == 'restricted':
                    warnings.append(f'Limited access active: {persona.get("label", persona_id)}')

        # Detect if we're in simulator-only mode (no LLM)
        if response_count > 0 and not citations:
            warnings.append('Running in simulator mode (LLM not connected)')

        return {
            'response_count': responses,
            'sources_used': list(source_categories),
            'coverage_percent': coverage_percent,
            'depth_score': depth_score,
            'citations_count': len(citations) if citations else 0,
            'warnings': warnings,
            'status': 'active',
        }
