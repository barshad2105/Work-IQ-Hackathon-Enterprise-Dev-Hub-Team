"""
Orchestrator - Coordinates parallel execution of all panel agents.
"""

import asyncio
from .suggestions_agent import SuggestionsAgent
from .timeline_agent import TimelineAgent
from .nextsteps_agent import NextStepsAgent
from .progress_agent import ProgressAgent


class PanelOrchestrator:
    """Orchestrates parallel execution of all panel agents."""

    @staticmethod
    async def orchestrate(
        scenario,
        persona_id: str = None,
        response_count: int = 0,
        citations: list = None,
        conversation_history: list = None,
        last_response: str = None,
        timeout: float = 5.0
    ) -> dict:
        """
        Run all agents in parallel and aggregate results.
        
        Args:
            scenario: Loaded scenario object
            persona_id: Active persona ID
            response_count: Number of responses in session
            citations: All citations from responses
            conversation_history: Full conversation history
            last_response: Most recent assistant response
            timeout: Timeout per agent in seconds
            
        Returns:
            Aggregated result object with all panel data
        """
        
        try:
            # Create tasks for all agents to run in parallel
            tasks = [
                asyncio.create_task(
                    asyncio.to_thread(
                        SuggestionsAgent.generate,
                        scenario,
                        persona_id,
                        conversation_history
                    )
                ),
                asyncio.create_task(
                    asyncio.to_thread(
                        TimelineAgent.generate,
                        scenario,
                        persona_id,
                        conversation_history,
                        citations
                    )
                ),
                asyncio.create_task(
                    asyncio.to_thread(
                        NextStepsAgent.generate,
                        scenario,
                        persona_id,
                        last_response,
                        conversation_history
                    )
                ),
                asyncio.create_task(
                    asyncio.to_thread(
                        ProgressAgent.generate,
                        scenario,
                        persona_id,
                        response_count,
                        citations,
                        conversation_history
                    )
                ),
            ]

            # Wait for all tasks with timeout
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )

            suggestions, timeline, nextsteps, progress = results

            # Handle any exceptions from individual agents
            suggestions = suggestions if not isinstance(suggestions, Exception) else []
            timeline = timeline if not isinstance(timeline, Exception) else []
            nextsteps = nextsteps if not isinstance(nextsteps, Exception) else []
            progress = progress if not isinstance(progress, Exception) else {}

            return {
                'success': True,
                'suggestions': suggestions or [],
                'timeline': timeline or [],
                'nextsteps': nextsteps or [],
                'progress': progress or {},
            }

        except asyncio.TimeoutError:
            # Fallback to synchronous execution if async times out
            return PanelOrchestrator._fallback_orchestrate(
                scenario, persona_id, response_count, citations, conversation_history, last_response
            )
        except Exception as e:
            print(f'[ORCHESTRATOR] Error: {e}')
            return PanelOrchestrator._fallback_orchestrate(
                scenario, persona_id, response_count, citations, conversation_history, last_response
            )

    @staticmethod
    def _fallback_orchestrate(scenario, persona_id, response_count, citations, conversation_history, last_response) -> dict:
        """Fallback synchronous execution if async fails."""
        return {
            'success': True,
            'suggestions': SuggestionsAgent.generate(scenario, persona_id, conversation_history),
            'timeline': TimelineAgent.generate(scenario, persona_id, conversation_history, citations),
            'nextsteps': NextStepsAgent.generate(scenario, persona_id, last_response, conversation_history),
            'progress': ProgressAgent.generate(scenario, persona_id, response_count, citations, conversation_history),
        }
