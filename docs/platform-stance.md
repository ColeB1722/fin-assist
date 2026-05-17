# Platform Stance — historical pointer

**Status:** retired 2026-05-17. Decisions migrated; this file is a pointer to their new homes.

This file *was* a decision-frame document under the experimental `docs/<decision>.md` lifecycle defined in [`AGENTS.md`](../AGENTS.md) §Context Strategy. It hosted the strategic decision frame for fin-assist's relationship to the broader agent ecosystem — protocol surfaces, CLI stance, workspace-split timing, dev-REPL feature line — across seven questions (Q1–Q7) and five working sessions in May 2026.

All decisions resolved and migrated:

- **Durable architectural claims** (deliverables shape, inbound protocol surfaces, the CLI's dev-tool role) → [`architecture.md`](architecture.md) sections *Deliverables: Hub vs CLI* and *Inbound protocol surfaces*.
- **Decision rows + rationale** (Q1 integration direction, Q2 protocol surfaces, Q3 CLI as dev tool, Q4 protocol-peer-not-BFF, Q5 ACP-server first, Q7 verification-only dev REPL with calibration examples) → [`decisions.md`](decisions.md) §*Platform stance*.
- **Q6 roadmap reconciliation** (which milestones changed, what closed, where ACP-server lands) → executed as the 2026-05-17 issue-hygiene pass; the live state is the GitHub milestone list. See [#162](https://github.com/ColeB1722/fin-assist/issues/162) for the ACP-server first cut.

**Why this stub exists rather than a deletion:** ~13 GitHub issue comments filed during the hygiene pass link to `docs/platform-stance.md`. A stub makes those links resolve to a useful redirect instead of a 404; the working-notes archaeology (§6 dated session logs, full options-considered for each question, the meta-observations) is preserved in git history.

**To read the full archaeology:** `git log -p -- docs/platform-stance.md` recovers every version of the file, including the final pre-retirement state with all seven questions, recorded thinking, and five working-session notes.
