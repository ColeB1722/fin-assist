"""Tests for the Skills API — SkillDefinition, SkillCatalog, SkillLoader."""

from __future__ import annotations

from fin_assist.agents.skills import SkillCatalog, SkillDefinition, SkillLoader
from fin_assist.agents.tools import ApprovalPolicy, ApprovalRule
from fin_assist.config.schema import ApprovalConfig, ApprovalRuleConfig, SkillConfig


def _make_skill(name: str = "test", **overrides) -> SkillDefinition:
    defaults = {
        "name": name,
        "description": f"Test skill: {name}",
        "tools": [],
    }
    defaults.update(overrides)
    return SkillDefinition(**defaults)


class TestSkillDefinition:
    def test_stores_fields(self) -> None:
        skill = SkillDefinition(
            name="commit",
            description="Generate commit messages",
            tools=["git", "read_file"],
            prompt_template="git-commit",
            entry_prompt="Analyze changes and commit",
            context="Use conventional commits",
        )
        assert skill.name == "commit"
        assert skill.tools == ["git", "read_file"]
        assert skill.prompt_template == "git-commit"
        assert skill.entry_prompt == "Analyze changes and commit"

    def test_approval_policy_defaults_none(self) -> None:
        skill = _make_skill()
        assert skill.approval_policy is None

    def test_serving_modes_defaults_none(self) -> None:
        skill = _make_skill(serving_modes=None)
        assert skill.serving_modes is None


class TestSkillCatalog:
    def test_empty_catalog_renders_empty_string(self) -> None:
        catalog = SkillCatalog()
        assert catalog.render() == ""

    def test_renders_available_skills(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit", description="Commit changes", tools=["git"]))
        catalog.add(_make_skill("pr", description="Create PR", tools=["gh"]))
        text = catalog.render()
        assert "**commit**" in text
        assert "**pr**" in text
        assert "Commit changes" in text
        assert "Create PR" in text
        assert "load_skill" in text

    def test_loaded_skills_excluded_from_catalog(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit", description="Commit changes"))
        catalog.add(_make_skill("pr", description="Create PR"))
        catalog.mark_loaded("commit")
        text = catalog.render()
        assert "commit" not in text
        assert "pr" in text

    def test_available_skills_excludes_loaded(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit"))
        catalog.mark_loaded("commit")
        assert catalog.available_skills() == []

    def test_available_skills_returns_unloaded(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit"))
        catalog.add(_make_skill("pr"))
        catalog.mark_loaded("commit")
        available = catalog.available_skills()
        assert len(available) == 1
        assert available[0].name == "pr"

    def test_render_shows_tools(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit", tools=["git", "read_file"]))
        text = catalog.render()
        assert "git" in text
        assert "read_file" in text

    def test_all_loaded_renders_empty(self) -> None:
        catalog = SkillCatalog()
        catalog.add(_make_skill("commit"))
        catalog.mark_loaded("commit")
        assert catalog.render() == ""


class TestSkillLoader:
    def test_load_from_config(self) -> None:
        config = SkillConfig(
            description="Commit changes",
            tools=["git", "read_file"],
            prompt_template="git-commit",
            entry_prompt="Analyze and commit",
        )
        loader = SkillLoader()
        skill = loader.load_from_config("commit", config)
        assert skill.name == "commit"
        assert skill.description == "Commit changes"
        assert skill.tools == ["git", "read_file"]
        assert skill.prompt_template == "git-commit"
        assert skill.entry_prompt == "Analyze and commit"

    def test_load_from_config_with_approval(self) -> None:
        config = SkillConfig(
            description="Git skill",
            tools=["git"],
            approval=ApprovalConfig(
                default="always",
                rules=[
                    ApprovalRuleConfig(pattern="git diff", mode="never"),
                    ApprovalRuleConfig(
                        pattern="git push *", mode="always", reason="Push needs approval"
                    ),
                ],
            ),
        )
        loader = SkillLoader()
        skill = loader.load_from_config("git", config)
        assert skill.approval_policy is not None
        assert skill.approval_policy.default == "always"
        assert len(skill.approval_policy.rules) == 2

        mode, _ = skill.approval_policy.evaluate("git diff")
        assert mode == "never"

        mode, reason = skill.approval_policy.evaluate("git push origin main")
        assert mode == "always"
        assert reason == "Push needs approval"

    def test_load_from_config_without_approval(self) -> None:
        config = SkillConfig(description="Read-only skill", tools=["read_file"])
        loader = SkillLoader()
        skill = loader.load_from_config("read", config)
        assert skill.approval_policy is None

    def test_load_all_from_agent_config(self) -> None:
        skills_config = {
            "commit": SkillConfig(description="Commit", tools=["git"]),
            "pr": SkillConfig(description="PR", tools=["gh"]),
        }
        loader = SkillLoader()
        skills = loader.load_all_from_agent_config(skills_config)
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"commit", "pr"}

    def test_resolve_tools_with_registry(self) -> None:
        from fin_assist.agents.tools import ToolRegistry, ToolDefinition

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="git",
                description="Git tool",
                callable=lambda: "ok",
                parameters_schema={"type": "object"},
            )
        )
        registry.register(
            ToolDefinition(
                name="read_file",
                description="Read file",
                callable=lambda: "ok",
                parameters_schema={"type": "object"},
            )
        )
        loader = SkillLoader(tool_registry=registry)
        skill = _make_skill("commit", tools=["git", "read_file", "nonexistent"])
        resolved = loader.resolve_tools(skill)
        names = {t.name for t in resolved}
        assert names == {"git", "read_file"}

    def test_resolve_tools_without_registry(self) -> None:
        loader = SkillLoader()
        skill = _make_skill("commit", tools=["git"])
        assert loader.resolve_tools(skill) == []

    def test_load_from_config_preserves_context(self) -> None:
        config = SkillConfig(
            description="Git skill",
            tools=["git"],
            context="Use conventional commits format.",
        )
        loader = SkillLoader()
        skill = loader.load_from_config("commit", config)
        assert skill.context == "Use conventional commits format."

    def test_load_from_config_preserves_serving_modes(self) -> None:
        config = SkillConfig(
            description="Summarize skill",
            tools=["git"],
            serving_modes=["do", "talk"],
        )
        loader = SkillLoader()
        skill = loader.load_from_config("summarize", config)
        assert skill.serving_modes == ["do", "talk"]


class TestSkillMdLoader:
    def test_parse_minimal_skill_md(self, tmp_path) -> None:
        skill_dir = tmp_path / "commit"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: commit\n"
            "description: Generate commit messages\n"
            "allowed-tools:\n"
            "  - git\n"
            "  - read_file\n"
            "---\n"
            "Use conventional commits format.\n"
        )
        loader = SkillLoader()
        skill = loader.load_from_skill_md(skill_dir / "SKILL.md")
        assert skill.name == "commit"
        assert skill.description == "Generate commit messages"
        assert skill.tools == ["git", "read_file"]
        assert "conventional commits" in skill.context

    def test_name_defaults_to_directory_name(self, tmp_path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: A skill\n---\nBody text.\n")
        loader = SkillLoader()
        skill = loader.load_from_skill_md(skill_dir / "SKILL.md")
        assert skill.name == "my-skill"

    def test_parse_with_approval_rules(self, tmp_path) -> None:
        skill_dir = tmp_path / "git"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: git\n"
            "allowed-tools:\n"
            "  - git\n"
            "metadata:\n"
            "  fin-assist:\n"
            "    approval:\n"
            "      default: always\n"
            "      rules:\n"
            "        - pattern: 'git diff'\n"
            "          mode: never\n"
            "        - pattern: 'git push *'\n"
            "          mode: always\n"
            "          reason: Pushing needs approval\n"
            "---\n"
            "Git workflow instructions.\n"
        )
        loader = SkillLoader()
        skill = loader.load_from_skill_md(skill_dir / "SKILL.md")
        assert skill.approval_policy is not None
        mode, _ = skill.approval_policy.evaluate("git diff")
        assert mode == "never"
        mode, reason = skill.approval_policy.evaluate("git push origin main")
        assert mode == "always"
        assert reason == "Pushing needs approval"

    def test_parse_with_fin_assist_extensions(self, tmp_path) -> None:
        skill_dir = tmp_path / "commit"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: commit\n"
            "metadata:\n"
            "  fin-assist:\n"
            "    prompt-template: git-commit\n"
            "    entry-prompt: Analyze and commit\n"
            "    serving-modes:\n"
            "      - do\n"
            "---\n"
            "Body.\n"
        )
        loader = SkillLoader()
        skill = loader.load_from_skill_md(skill_dir / "SKILL.md")
        assert skill.prompt_template == "git-commit"
        assert skill.entry_prompt == "Analyze and commit"
        assert skill.serving_modes == ["do"]

    def test_parse_no_frontmatter_raises(self, tmp_path) -> None:
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Just some text without frontmatter.\n")
        loader = SkillLoader()
        import pytest

        with pytest.raises(ValueError, match="YAML frontmatter"):
            loader.load_from_skill_md(skill_dir / "SKILL.md")

    def test_parse_empty_frontmatter(self, tmp_path) -> None:
        skill_dir = tmp_path / "minimal"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n---\nBody text only.\n")
        loader = SkillLoader()
        skill = loader.load_from_skill_md(skill_dir / "SKILL.md")
        assert skill.name == "minimal"
        assert skill.context == "Body text only."

    def test_discover_skill_md_files(self, tmp_path, monkeypatch) -> None:
        from fin_assist.agents import skills as skills_mod

        project_dir = tmp_path / "project"
        user_dir = tmp_path / "user"

        (project_dir / "commit").mkdir(parents=True)
        (project_dir / "commit" / "SKILL.md").write_text("---\n---\nProject commit.\n")

        (user_dir / "commit").mkdir(parents=True)
        (user_dir / "commit" / "SKILL.md").write_text("---\n---\nUser commit.\n")

        (user_dir / "pr").mkdir(parents=True)
        (user_dir / "pr" / "SKILL.md").write_text("---\n---\nUser PR.\n")

        monkeypatch.setattr(skills_mod, "_PROJECT_SKILLS_DIR", project_dir)
        monkeypatch.setattr(skills_mod, "_USER_SKILLS_DIR", user_dir)

        loader = SkillLoader()
        found = loader.discover_skill_md_files()
        assert "commit" in found
        assert "pr" in found
        assert found["commit"].parent.parent == project_dir

    def test_discover_skips_non_directories(self, tmp_path, monkeypatch) -> None:
        from fin_assist.agents import skills as skills_mod

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "not-a-dir.txt").write_text("not a skill")

        monkeypatch.setattr(skills_mod, "_PROJECT_SKILLS_DIR", skills_dir)
        monkeypatch.setattr(skills_mod, "_USER_SKILLS_DIR", tmp_path / "nonexistent")

        loader = SkillLoader()
        found = loader.discover_skill_md_files()
        assert found == {}


class TestSkillManager:
    def test_load_skill(self) -> None:
        from fin_assist.agents.skills import SkillManager

        skills = [
            _make_skill("commit", description="Commit changes", tools=["git"]),
            _make_skill("pr", description="Create PR", tools=["gh"]),
        ]
        mgr = SkillManager(skills=skills)
        result = mgr.load_skill("commit")
        assert "commit" in result
        assert "loaded" in result.lower()

    def test_load_unknown_skill(self) -> None:
        from fin_assist.agents.skills import SkillManager

        mgr = SkillManager(skills=[_make_skill("commit")])
        result = mgr.load_skill("nonexistent")
        assert "Unknown skill" in result

    def test_load_already_loaded_skill(self) -> None:
        from fin_assist.agents.skills import SkillManager

        mgr = SkillManager(skills=[_make_skill("commit")])
        mgr.load_skill("commit")
        result = mgr.load_skill("commit")
        assert "already loaded" in result.lower()

    def test_is_loaded(self) -> None:
        from fin_assist.agents.skills import SkillManager

        mgr = SkillManager(skills=[_make_skill("commit")])
        assert mgr.is_loaded("commit") is False
        mgr.load_skill("commit")
        assert mgr.is_loaded("commit") is True

    def test_loaded_tool_names(self) -> None:
        from fin_assist.agents.skills import SkillManager

        skills = [
            _make_skill("commit", tools=["git", "read_file"]),
            _make_skill("pr", tools=["gh", "git"]),
        ]
        mgr = SkillManager(skills=skills)
        mgr.load_skill("commit")
        mgr.load_skill("pr")
        assert mgr.loaded_tool_names() == ["git", "read_file", "gh"]

    def test_available_skills_excludes_loaded(self) -> None:
        from fin_assist.agents.skills import SkillManager

        skills = [_make_skill("commit"), _make_skill("pr")]
        mgr = SkillManager(skills=skills)
        mgr.load_skill("commit")
        available = mgr.available_skills()
        assert len(available) == 1
        assert available[0].name == "pr"

    def test_catalog_text_updates_after_load(self) -> None:
        from fin_assist.agents.skills import SkillManager

        skills = [_make_skill("commit", description="Commit")]
        mgr = SkillManager(skills=skills)
        assert "commit" in mgr.catalog_text()
        mgr.load_skill("commit")
        assert mgr.catalog_text() == ""

    def test_make_load_skill_callable(self) -> None:
        import asyncio
        from fin_assist.agents.skills import SkillManager

        mgr = SkillManager(skills=[_make_skill("commit")])
        callable_fn = mgr.make_load_skill_callable()
        assert callable_fn.__name__ == "load_skill"
        result = asyncio.get_event_loop().run_until_complete(callable_fn("commit"))
        assert "loaded" in result.lower()

    def test_from_agent_config(self) -> None:
        from fin_assist.agents.skills import SkillManager

        agent_config = type(
            "FakeConfig",
            (),
            {
                "skills": {
                    "commit": SkillConfig(description="Commit", tools=["git"]),
                },
            },
        )()
        mgr = SkillManager.from_agent_config(agent_config)
        assert len(mgr.available_skills()) == 1
        assert mgr.available_skills()[0].name == "commit"
