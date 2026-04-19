"""Tests for the Skill system."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path

from nexusagent.skills.models import Skill
from nexusagent.skills.registry import SkillRegistry
from nexusagent.skills.matcher import SkillMatcher
from nexusagent.skills.executor import SkillExecutor


class TestSkill:
    """Test Skill model and file parsing."""

    def test_parse_skill_with_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deploy.md"
            path.write_text("""---
name: deploy
description: "Deploy to production"
version: "2.0"
---

# Deploy Skill

## Steps
1. Build
2. Deploy
""", encoding="utf-8")
            skill = Skill.from_file(path)

        assert skill.name == "deploy"
        assert skill.description == "Deploy to production"
        assert skill.version == "2.0"
        assert "# Deploy Skill" in skill.content
        assert "1. Build" in skill.content

    def test_parse_skill_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simple.md"
            path.write_text("# Simple Skill\n\nJust a simple skill without frontmatter.", encoding="utf-8")
            skill = Skill.from_file(path)

        assert skill.name == "simple"
        assert skill.description == ""
        assert "# Simple Skill" in skill.content

    def test_parse_skill_single_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quoted.md"
            path.write_text("---\ndescription: 'Single quoted description'\n---\n\nBody", encoding="utf-8")
            skill = Skill.from_file(path)

        assert skill.description == "Single quoted description"


class TestSkillRegistry:
    """Test Skill discovery and loading."""

    def test_scan_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "deploy.md").write_text("""---
name: deploy
description: "Deploy to production"
---

Deploy steps
""")
            Path(tmp, "review.md").write_text("""---
name: review
description: "Code review"
---

Review steps
""")
            registry = SkillRegistry()
            registry.add_directory(Path(tmp))
            registry.scan()

            assert len(registry.skills) == 2
            assert "deploy" in registry.skills
            assert "review" in registry.skills

    def test_project_overrides_global(self):
        with tempfile.TemporaryDirectory() as global_dir:
            with tempfile.TemporaryDirectory() as project_dir:
                # Global skill
                Path(global_dir, "deploy.md").write_text(
                    '---\ndescription: "Global deploy"\n---\nGlobal'
                )
                # Project skill (same name)
                Path(project_dir, "deploy.md").write_text(
                    '---\ndescription: "Project deploy"\n---\nProject'
                )

                registry = SkillRegistry()
                registry.add_directory(Path(global_dir), scope="global")
                registry.add_directory(Path(project_dir), scope="project")
                registry.scan()

                assert len(registry.skills) == 1
                assert registry.skills["deploy"].scope == "project"

    def test_empty_directory(self):
        registry = SkillRegistry()
        registry.add_directory(Path("/nonexistent/path"))
        registry.scan()  # Should not raise
        assert len(registry.skills) == 0

    def test_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SkillRegistry()
            registry.add_directory(Path(tmp))
            registry.scan()
            assert len(registry.skills) == 0

            # Add a skill file
            Path(tmp, "test.md").write_text("# Test\n\nBody")
            registry.reload()
            assert "test" in registry.skills


class TestSkillMatcher:
    """Test skill matching from user input."""

    @pytest.fixture
    def registry(self):
        reg = SkillRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "deploy.md").write_text(
                '---\ndescription: "Build, test, and deploy to production"\n---\nDeploy steps',
                encoding="utf-8",
            )
            Path(tmp, "code-review.md").write_text(
                '---\ndescription: "Review recent git changes for code quality"\n---\nReview steps',
                encoding="utf-8",
            )
            reg.add_directory(Path(tmp))
            reg.scan()
        return reg

    def test_slash_command_match(self, registry):
        matcher = SkillMatcher(registry)
        enhanced, skill = matcher.match("/deploy")

        assert skill is not None
        assert skill.name == "deploy"
        assert "deploy" in enhanced.lower()

    def test_slash_command_with_args(self, registry):
        matcher = SkillMatcher(registry)
        enhanced, skill = matcher.match("/deploy --staging")

        assert skill is not None
        assert "--staging" in enhanced

    def test_keyword_match(self, registry):
        matcher = SkillMatcher(registry)
        enhanced, skill = matcher.match("use deploy skill please")

        assert skill is not None
        assert skill.name == "deploy"

    def test_no_match(self, registry):
        matcher = SkillMatcher(registry)
        result, skill = matcher.match("hello world")

        assert skill is None
        assert result == "hello world"

    def test_description_keyword_match(self, registry):
        matcher = SkillMatcher(registry)
        enhanced, skill = matcher.match("deploy to production")

        assert skill is not None
        assert skill.name == "deploy"


class TestSkillExecutor:
    """Test skill execution and prompt injection."""

    @pytest.fixture
    def setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "test.md").write_text(
                '---\ndescription: "Test skill description"\n---\n## Steps\n1. Do something\n',
                encoding="utf-8",
            )
            reg = SkillRegistry()
            reg.add_directory(Path(tmp))
            reg.scan()
            matcher = SkillMatcher(reg)
            executor = SkillExecutor(reg, matcher)
            return executor

    def test_execute_with_skill_match(self, setup):
        executor = setup
        enhanced, skill = executor.process_input("/test")

        assert skill is not None
        assert skill.name == "test"
        assert "Do something" in enhanced
        assert executor.active_skill == skill

    def test_execute_no_match(self, setup):
        executor = setup
        result, skill = executor.process_input("just a normal message")

        assert skill is None
        assert result == "just a normal message"
