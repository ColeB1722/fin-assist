r"""Skills API — the core abstraction for tool organization in fin-assist.

An agent is a collection of skills within an environment.  A skill curates
tools, approval rules, context injection text, and prompt steering.  Skills
are loaded additively — once loaded, a skill's tools stay active for the
session.

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
3. Approval policies on skills override the tool's default policy for
   tools within that skill.
4. Agent-driven loading: the agent sees a catalog and calls
   ``load_skill(name)`` to activate skills.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fin_assist.agents.tools import ApprovalPolicy, ApprovalRule
from fin_assist.paths import DATA_DIR

if TYPE_CHECKING:
    from fin_assist.agents.tools import ToolDefinition, ToolRegistry
    from fin_assist.config.schema import AgentConfig, ServingMode, SkillConfig

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
    """

    name: str
    description: str
    tools: list[str]
    approval_policy: ApprovalPolicy | None = None
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
        approval_policy = None
        if config.approval is not None:
            rules = [
                ApprovalRule(pattern=r.pattern, mode=r.mode, reason=r.reason)
                for r in config.approval.rules
            ]
            approval_policy = ApprovalPolicy(
                mode=config.approval.default,
                default=config.approval.default,
                rules=rules,
            )

        return SkillDefinition(
            name=name,
            description=config.description,
            tools=config.tools,
            approval_policy=approval_policy,
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

    def resolve_tools(
        self,
        skill: SkillDefinition,
    ) -> list[ToolDefinition]:
        """Resolve a skill's tool names to ``ToolDefinition`` instances.

        Unknown tool names are silently skipped (matching the existing
        ``ToolRegistry.get_for_agent`` behavior).
        """
        if self._tool_registry is None:
            return []
        return self._tool_registry.get_for_agent(skill.tools)

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
            metadata.fin-assist.approval (dict): ApprovalConfig fields
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

        approval_policy = None
        approval_cfg = fin_meta.get("approval")
        if approval_cfg is not None and isinstance(approval_cfg, dict):
            raw_rules = approval_cfg.get("rules", [])
            rules = []
            for r in raw_rules:
                if not isinstance(r, dict) or "pattern" not in r or "mode" not in r:
                    raise ValueError(
                        f"Invalid approval rule in {path}: "
                        f"each rule must have 'pattern' and 'mode', got {r}"
                    )
                rules.append(
                    ApprovalRule(
                        pattern=r["pattern"],
                        mode=r["mode"],
                        reason=r.get("reason"),
                    )
                )
            approval_policy = ApprovalPolicy(
                mode=approval_cfg.get("default", "always"),
                default=approval_cfg.get("default", "always"),
                rules=rules,
            )

        prompt_template = fin_meta.get("prompt-template", "")
        entry_prompt = fin_meta.get("entry-prompt", "")
        serving_modes = fin_meta.get("serving-modes")

        return SkillDefinition(
            name=name,
            description=description,
            tools=tools,
            approval_policy=approval_policy,
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

    @classmethod
    def from_agent_config(
        cls,
        agent_config: AgentConfig,
        tool_registry: ToolRegistry | None = None,
    ) -> SkillManager:
        """Create a SkillManager from an AgentConfig's skills dict."""
        loader = SkillLoader(tool_registry=tool_registry)
        skills = loader.load_all_from_agent_config(agent_config.skills)
        return cls(skills=skills, tool_registry=tool_registry)

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

    def available_skills(self) -> list[SkillDefinition]:
        return self._catalog.available_skills()

    def loaded_tool_names(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for skill in self.loaded_skills():
            for tool_name in skill.tools:
                if tool_name not in seen:
                    seen.add(tool_name)
                    result.append(tool_name)
        return result

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
