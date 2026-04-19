"""Skill matcher: maps user input to the most relevant skill."""

from __future__ import annotations

from nexusagent.skills.registry import SkillRegistry


class SkillMatcher:
    """
    Match user input to a skill via three levels:
    1. Exact slash command: /deploy -> "deploy" skill
    2. Keyword in name: "use deploy skill" -> "deploy" skill
    3. Keyword in description: "deploy the app" -> deploy skill (if "deploy" in description)
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def match(self, user_input: str) -> tuple[str | None, Skill | None]:
        """
        Match user input to a skill.

        Returns: (modified_input, matched_skill) or (original_input, None)
        """
        # 1. Slash command: /deploy
        if user_input.startswith("/"):
            cmd = user_input[1:].split()[0].lower()
            rest = user_input[1:].split(maxsplit=1)
            args = rest[1] if len(rest) > 1 else ""
            skill = self.registry.get(cmd)
            if skill:
                enhanced = (
                    f"Please follow the '{skill.name}' skill instructions:\n\n"
                    f"{skill.content}\n\n"
                    f"Additional context: {args}"
                )
                return enhanced, skill

        # 2. Keyword match in skill names
        input_lower = user_input.lower()
        for name, skill in self.registry.skills.items():
            if name.lower() in input_lower:
                enhanced = (
                    f"Please follow the '{skill.name}' skill instructions:\n\n"
                    f"{skill.content}\n\n"
                    f"User request: {user_input}"
                )
                return enhanced, skill

        # 3. Description keyword match (words longer than 3 chars)
        for skill in self.registry.skills.values():
            if skill.description:
                desc_words = {
                    w.lower() for w in skill.description.lower().split() if len(w) > 3
                }
                if any(w in desc_words for w in input_lower.split()):
                    enhanced = (
                        f"Please follow the '{skill.name}' skill instructions:\n\n"
                        f"{skill.content}\n\n"
                        f"User request: {user_input}"
                    )
                    return enhanced, skill

        return user_input, None
