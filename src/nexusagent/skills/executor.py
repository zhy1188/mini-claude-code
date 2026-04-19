"""Skill executor: orchestrates skill matching and instruction injection."""

from __future__ import annotations

from nexusagent.skills.matcher import SkillMatcher
from nexusagent.skills.registry import SkillRegistry


class SkillExecutor:
    """
    Match user input to skills and inject skill instructions into the prompt.

    The matched skill's content is prepended to the user's input, instructing
    the LLM to follow the defined steps.
    """

    def __init__(self, registry: SkillRegistry, matcher: SkillMatcher):
        self.registry = registry
        self.matcher = matcher
        self.active_skill = None

    def process_input(self, user_input: str) -> tuple[str, object | None]:
        """
        Process user input, returning enhanced prompt if a skill matches.

        Returns: (enhanced_input, matched_skill) or (original_input, None)
        """
        enhanced, skill = self.matcher.match(user_input)
        if skill:
            self.active_skill = skill
            return enhanced, skill
        return user_input, None
