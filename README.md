# agents

Shared agent skills, consumed by every agent runtime I use:

- **Claude Code** — reads `~/.agents/skills/` (symlink created by `make install`)
- **Hermes** (homelab, the-gibson) — reads `/opt/agents/skills` (a read-only
  mount of this repo's checkout at `/mnt/nvme/homelab/hermes/agents`, updated
  by `make deploy-hermes` in home.abelson.live via `ansible.builtin.git`)

## Layout

```text
skills/
  <skill-name>/
    SKILL.md        # required — frontmatter + instructions
    scripts/        # optional — helper scripts, run via uv
    references/     # optional — deeper docs, loaded on demand
```

## SKILL.md conventions

Follows the [agentskills.io](https://agentskills.io) open standard (works in
both Claude Code and Hermes):

```markdown
---
name: my-skill
description: What it does and when to use it (keep ≤60 chars)
---

# My Skill
## When to Use
## Procedure
## Pitfalls
## Verification
```

- `description` is what agents use to decide relevance — make it specific,
  keep it short (Hermes house style caps it at 60 chars).
- Progressive disclosure: keep SKILL.md lean; push detail into
  `references/` files the agent loads only when needed.
- Python helpers run via **uv**: give scripts inline script metadata
  (`# /// script` blocks) so `uv run scripts/foo.py` just works — no
  requirements.txt, no venv setup in instructions.
- Don't symlink skill directories from other repos — symlinks don't
  resolve in git checkouts on other machines or inside containers. Commit
  real content.

## Install (local, for Claude Code)

```sh
make install   # symlinks this repo to ~/.agents
```
