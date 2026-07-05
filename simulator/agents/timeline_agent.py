"""
Timeline Agent - Builds chronological timeline for the TIMELINE panel.
"""

from datetime import datetime


class TimelineAgent:
    """Generates timeline events from scenario data and conversation history."""

    @staticmethod
    def generate(scenario, persona_id: str = None, conversation_history: list = None, citations: list = None) -> list:
        """
        Generate timeline entries based on scenario data.
        
        Args:
            scenario: Loaded scenario object
            persona_id: Active persona ID
            conversation_history: List of previous messages (for message timeline)
            citations: List of citations from responses (for evidence timeline)
            
        Returns:
            List of timeline entry objects {timestamp, label, type, icon}
        """
        timeline = []

        # Add conversation start
        timeline.append({
            'timestamp': datetime.now().isoformat(),
            'label': 'Session started',
            'type': 'session',
            'icon': '🚀',
        })

        # Add key meetings from scenario if available
        try:
            meetings = getattr(scenario, 'meetings', [])
            if meetings and isinstance(meetings, list):
                # Add most recent meetings (limit to 3)
                for meeting in meetings[:3]:
                    if isinstance(meeting, dict):
                        m_date = meeting.get('date') or meeting.get('timestamp')
                        m_title = meeting.get('title') or meeting.get('subject', 'Meeting')
                        if m_date:
                            timeline.append({
                                'timestamp': m_date,
                                'label': m_title[:50],
                                'type': 'meeting',
                                'icon': '📅',
                            })
        except Exception:
            pass

        # Add key emails from scenario
        try:
            emails = getattr(scenario, 'emails', [])
            if emails and isinstance(emails, list):
                # Add most recent emails (limit to 2)
                for email in emails[:2]:
                    if isinstance(email, dict):
                        e_date = email.get('date') or email.get('timestamp')
                        e_subject = email.get('subject', 'Email')
                        if e_date:
                            timeline.append({
                                'timestamp': e_date,
                                'label': e_subject[:50],
                                'type': 'email',
                                'icon': '📧',
                            })
        except Exception:
            pass

        # Add conversation turns if provided
        if conversation_history and isinstance(conversation_history, list):
            for i, msg in enumerate(conversation_history):
                if isinstance(msg, dict):
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')[:40]
                    if content:
                        timeline.append({
                            'timestamp': datetime.now().isoformat(),
                            'label': f'{role.title()}: {content}...',
                            'type': 'message',
                            'icon': '💬',
                        })

        # Sort by timestamp (most recent first)
        try:
            timeline.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        except Exception:
            pass

        # Limit to 8 entries
        return timeline[:8]
