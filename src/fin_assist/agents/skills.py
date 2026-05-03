r"""Skills API — the core abstraction for tool organization in fin-assist.

An agent is a collection of skills within an environment.  A skill curates
tools, context injection text, and prompt steering.  Skills are loaded
additively — once loaded, a skill's tools stay active for the session.

Approval policies are defined at the agent level via
``AgentConfig.tool_policies``, not per-skill.  This eliminates merge
conflicts when multiple skills reference the same tool.

Key types:

- ``SkillDefinition`` — runtime representation of a resolved skill
- ``SkillCatalog`` — generates the skill catalog text injected into the
  agent's system prompt for agent-driven skill discovery
- ``SkillLoader`` — resolves ``SkillConfig`` (from config.toml) or
  SKILL.md files into ``SkillDefinition`` instances

Design decisions (see architecture.md for full rationale):

1. Skills are additive.  No skill unloading in v0.1.
2. Tools are shared across skills.  Name collisions (two different
   ``ToolDefinition``\s with the same name) are a config error.
3. Approval policies are agent-level, not skill-level.  Each tool has
   exactly one policy definition — no merge/conflict.
4. Agent-driven loading: the agent sees a catalog and calls
   ``load_skill(name)`` to activate skills.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fin_assist.paths import DATA_DIR

if TYPE_CHECKING:
    from fin_assist.agents.tools import ToolRegistry
    from fin_assist.config.schema import ServingMode, SkillConfig

logger = logging.getLogger(__name__)

_SKILL_MD_PATTERN = re.compile(
    r"^---\s*\n(?P<frontmatter>.*?)\n?---\s*\n(?P<body>.*)",
    re.DOTALL,
)

_USER_SKILLS_DIR = Path.home() / ".config" / "fin" / "skills"
_PROJECT_SKILLS_DIR = DATA_DIR / "skills"


@dataclass
class SkillDefinition:
    """Runtime representation of a fully resolved skill.

    Created by ``SkillLoader`` from either a ``SkillConfig`` (config.toml)
    or a SKILL.md file.  Contains all the information the backend needs
    to register tools and inject context.

    Approval policies are defined at the agent level via
    ``AgentConfig.tool_policies``, not on the skill.
    """

    name: str
    description: str
    tools: list[str]
    prompt_template: str = ""
    entry_prompt: str = ""
    context: str = ""
    serving_modes: list[ServingMode] | None = None


@dataclass
class SkillCatalog:
    """Generates the skill catalog text for the agent's system prompt.

    The catalog is a concise summary of available (but not yet loaded)
    skills, formatted so the LLM can reason about which skill to load
    next.  Loaded skills are excluded from the catalog.
    """

    skills: list[SkillDefinition] = field(default_factory=list)
    loaded: set[str] = field(default_factory=set)

    def add(self, skill: SkillDefinition) -> None:
        self.skills.append(skill)

    def mark_loaded(self, name: str) -> None:
        self.loaded.add(name)

    def available_skills(self) -> list[SkillDefinition]:
        return [s for s in self.skills if s.name not in self.loaded]

    def render(self) -> str:
        """Render the catalog as text for the system prompt.

        Returns an empty string when no skills are available (so the
        catalog section can be omitted entirely from the prompt).
        """
        available = self.available_skills()
        if not available:
            return ""

        lines = ["## Available skills", ""]
        for skill in available:
            desc = skill.description or "(no description)"
            lines.append(f"- **{skill.name}**: {desc}")
            if skill.tools:
                lines.append(f"  Tools: {', '.join(skill.tools)}")
        lines.append("")
        lines.append("To activate a skill, use the `load_skill` tool with the skill name.")
        return "\n".join(lines)


class SkillLoader:
    """Resolves ``SkillConfig`` instances into ``SkillDefinition`` objects.

    Handles two sources:

    1. **Inline TOML config** — ``SkillConfig`` from ``config.toml``
    2. **SKILL.md files** — parsed from ``.fin/skills/`` or
       ``~/.config/fin/skills/`` (Phase 1.4)

    SKILL.md takes precedence for same-name skills.
    """

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self._tool_registry = tool_registry

    def load_from_config(self, name: str, config: SkillConfig) -> SkillDefinition:
        """Resolve a ``SkillConfig`` into a ``SkillDefinition``."""
        return SkillDefinition(
            name=name,
            description=config.description,
            tools=config.tools,
            prompt_template=config.prompt_template,
            entry_prompt=config.entry_prompt,
            context=config.context,
            serving_modes=config.serving_modes,
        )

    def load_all_from_agent_config(
        self,
        skills_config: dict[str, SkillConfig],
    ) -> list[SkillDefinition]:
        """Load all skills from an agent's config.

        Returns a list of ``SkillDefinition`` instances, one per entry
        in the ``skills`` dict.
        """
        return [self.load_from_config(name, cfg) for name, cfg in skills_config.items()]

    def load_from_skill_md(self, path: Path) -> SkillDefinition:
        """Parse a SKILL.md file and return a ``SkillDefinition``.

        SKILL.md format follows the agentskills.io open standard:

        - YAML frontmatter between ``---`` delimiters
        - Markdown body after the second ``---``

        Frontmatter fields (agentskills.io standard):
            name (str): Skill name (defaults to directory name)
            description (str): One-line description
            allowed-tools (list[str]): Tool names this skill uses

        fin-assist extensions live under ``metadata.fin-assist``:
            metadata.fin-assist.prompt-template (str): System prompt template
            metadata.fin-assist.entry-prompt (str): Entry prompt for do mode
            metadata.fin-assist.serving-modes (list[str]): Mode restrictions
        """
        import yaml

        text = path.read_text(encoding="utf-8")
        match = _SKILL_MD_PATTERN.match(text)
        if not match:
            raise ValueError(f"SKILL.md must start with YAML frontmatter: {path}")

        frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
        body = match.group("body").strip()

        name = frontmatter.get("name", path.parent.name)
        description = frontmatter.get("description", "")
        tools = frontmatter.get("allowed-tools", [])

        metadata = frontmatter.get("metadata", {})
        fin_meta = metadata.get("fin-assist", {}) if isinstance(metadata, dict) else {}

        prompt_template = fin_meta.get("prompt-template", "")
        entry_prompt = fin_meta.get("entry-prompt", "")
        serving_modes = fin_meta.get("serving-modes")

        return SkillDefinition(
            name=name,
            description=description,
            tools=tools,
            prompt_template=prompt_template,
            entry_prompt=entry_prompt,
            context=body,
            serving_modes=serving_modes,
        )

    def discover_skill_md_files(self) -> dict[str, Path]:
        """Discover SKILL.md files from project and user skill directories.

        Returns a dict mapping skill name → Path.  Project-level skills
        (``.fin/skills/<name>/SKILL.md``) take precedence over user-level
        skills (``~/.config/fin/skills/<name>/SKILL.md``).
        """
        found: dict[str, Path] = {}

        for skills_dir in (_USER_SKILLS_DIR, _PROJECT_SKILLS_DIR):
            if not skills_dir.is_dir():
                continue
            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if skill_md.is_file():
                    found[skill_dir.name] = skill_md

        return found


class SkillManager:
    """Manages skill loading and catalog for a single agent session.

    Tracks which skills are loaded, provides the ``load_skill`` tool
    callable, and generates the skill catalog for the system prompt.

    The manager is created per-agent and holds:
    - All available skills (from config + SKILL.md discovery)
    - A set of loaded skill names
    - A reference to the ToolRegistry for resolving tool definitions
    """

    def __init__(
        self,
        skills: list[SkillDefinition],
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._skills = {s.name: s for s in skills}
        self._loaded: set[str] = set()
        self._tool_registry = tool_registry
        self._catalog = SkillCatalog(skills=skills)

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def load_skill(self, name: str) -> str:
        """Load a skill by name, marking its tools as active.

        Returns a human-readable confirmation message.  If the skill
        is already loaded, returns a message indicating that.  If the
        skill doesn't exist, returns an error message.
        """
        skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(sorted(self._skills.keys())) or "none"
            return f"Unknown skill '{name}'. Available skills: {available}"

        if name in self._loaded:
            return f"Skill '{name}' is already loaded."

        self._loaded.add(name)
        self._catalog.mark_loaded(name)
        tools_str = ", ".join(skill.tools) if skill.tools else "none"
        return f"Skill '{name}' loaded. Tools now available: {tools_str}"

    def loaded_skills(self) -> list[SkillDefinition]:
        return [self._skills[n] for n in sorted(self._loaded) if n in self._skills]

    def loaded_tool_names(self) -> list[str]:
        """Return deduplicated tool names from all loaded skills."""
        seen: set[str] = set()
        result: list[str] = []
        for skill in self.loaded_skills():
            for tool_name in skill.tools:
                if tool_name not in seen:
                    seen.add(tool_name)
                    result.append(tool_name)
        return result

    def available_skills(self) -> list[SkillDefinition]:
        return self._catalog.available_skills()

    def catalog_text(self) -> str:
        return self._catalog.render()

    def make_load_skill_callable(self):
        """Return an async callable suitable for registration as a tool.

        The callable accepts a ``name`` parameter and delegates to
        ``self.load_skill()``.
        """

        async def _load_skill(name: str) -> str:
            return self.load_skill(name)

        _load_skill.__name__ = "load_skill"
        return _load_skill
