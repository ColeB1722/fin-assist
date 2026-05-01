from __future__ import annotations

import pytest

from fin_assist.agents.tools import ApprovalPolicy, ApprovalRule


class TestApprovalRule:
    def test_exact_match(self) -> None:
        rule = ApprovalRule(pattern="git diff", mode="never")
        assert rule.matches("git diff") is True

    def test_exact_no_match(self) -> None:
        rule = ApprovalRule(pattern="git diff", mode="never")
        assert rule.matches("git push") is False

    def test_wildcard_match(self) -> None:
        rule = ApprovalRule(pattern="git push *", mode="always")
        assert rule.matches("git push origin main") is True

    def test_wildcard_no_match(self) -> None:
        rule = ApprovalRule(pattern="git push *", mode="always")
        assert rule.matches("git diff") is False

    def test_glob_star_matches_everything(self) -> None:
        rule = ApprovalRule(pattern="*", mode="always")
        assert rule.matches("anything") is True
        assert rule.matches("") is True

    def test_prefix_wildcard(self) -> None:
        rule = ApprovalRule(pattern="git *", mode="never")
        assert rule.matches("git status") is True
        assert rule.matches("git log --oneline") is True
        assert rule.matches("gh pr list") is False


class TestApprovalPolicyEvaluate:
    def test_no_rules_returns_default(self) -> None:
        policy = ApprovalPolicy(mode="always", reason="requires approval")
        mode, reason = policy.evaluate("git push")
        assert mode == "always"
        assert reason == "requires approval"

    def test_no_rules_returns_mode_as_default(self) -> None:
        policy = ApprovalPolicy(mode="never")
        mode, _ = policy.evaluate("git diff")
        assert mode == "never"

    def test_first_matching_rule_wins(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            default="always",
            rules=[
                ApprovalRule(pattern="git diff", mode="never"),
                ApprovalRule(pattern="git *", mode="always", reason="git commands need approval"),
            ],
        )
        mode, reason = policy.evaluate("git diff")
        assert mode == "never"
        assert reason is None

    def test_falls_through_to_second_rule(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            default="always",
            rules=[
                ApprovalRule(pattern="git diff", mode="never"),
                ApprovalRule(pattern="git *", mode="always", reason="git commands need approval"),
            ],
        )
        mode, reason = policy.evaluate("git push")
        assert mode == "always"
        assert reason == "git commands need approval"

    def test_no_rule_matches_returns_default(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            default="always",
            rules=[
                ApprovalRule(pattern="git diff", mode="never"),
            ],
        )
        mode, _ = policy.evaluate("run_shell")
        assert mode == "always"

    def test_default_overrides_mode(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            default="never",
            rules=[],
        )
        mode, _ = policy.evaluate("anything")
        assert mode == "never"

    def test_default_defaults_to_mode(self) -> None:
        policy = ApprovalPolicy(mode="always")
        assert policy.default == "always"

    def test_default_set_explicitly(self) -> None:
        policy = ApprovalPolicy(mode="always", default="never")
        assert policy.default == "never"

    def test_empty_args_evaluation(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            rules=[
                ApprovalRule(pattern="", mode="never"),
                ApprovalRule(pattern="*", mode="always"),
            ],
        )
        mode, _ = policy.evaluate("")
        assert mode == "never"

    def test_rule_with_reason(self) -> None:
        policy = ApprovalPolicy(
            mode="always",
            rules=[
                ApprovalRule(
                    pattern="git push *", mode="always", reason="Pushing requires confirmation"
                ),
            ],
        )
        _, reason = policy.evaluate("git push origin main")
        assert reason == "Pushing requires confirmation"
