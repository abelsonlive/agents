---
name: homelab-deploy
description: |
  Update and deploy the homelab (home.abelson.live) from the the-gibson host.
  Use when asked to change a service's config, add a new service, roll out an
  update, restart/stop a service, check what's running, or read a service's
  logs. You author changes in the repo, push them, then deploy via the broker.
license: ISC
---

# Homelab deploy

You (Hermes) run bare-metal on **the-gibson** and are the trusted operator of
the `home.abelson.live` homelab. You do two things: **author changes** to the
config repo (edit → commit → push), and **deploy** them via the deploy broker.

The homelab is Ansible-driven: one directory per service under `compose/` (a
`docker-compose.yml.j2` + optional `.env.j2`), a matching role under
`ansible/roles/<svc>/`, a thin playbook `ansible/playbooks/<svc>.yml`, and
central vars in `ansible/inventory/group_vars/all/vars.yml` (ports, the
`caddy_services` list that drives both Caddy and Pi-hole DNS). Read
`AGENTS.md` and `docs/` in the repo before non-trivial changes.

## 1. Author changes (edit + push)

Clone/refresh the repo in your workspace and push over HTTPS using your
`GITLAB_TOKEN` (already in your environment):

```bash
cd /workspace
if [ ! -d home.abelson.live ]; then
  git clone "https://oauth2:${GITLAB_TOKEN}@gitlab.com/abelsonlive/home.abelson.live.git"
fi
cd home.abelson.live && git pull
# ...make your edits...
git add -A && git commit -m "clear message of what changed"
git push origin main
```

Deploys always come from `origin/main`, so **push before you deploy** — the
broker deploys exactly what's on `main`, never your uncommitted/unpushed work.

## 2. Deploy (via the broker)

The broker is the only privileged action available to you. It runs the real
Ansible deploy as `zero-cool` (which holds the vault password + fleet SSH — you
don't need them). Call it with:

```
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker <verb> [app] [tag]
```

| verb | what it does |
|---|---|
| `list` | list deployable playbooks (everything in the repo, minus the denylist) |
| `status [app]` | `docker compose ps` (all the-gibson apps, or one) |
| `logs <app> [lines]` | tail a service's container logs (default 100) |
| `deploy <app> [tag]` | pull `origin/main` and run `ansible/playbooks/<app>.yml` |
| `restart <app>` | `docker compose restart` (the-gibson docker apps only) |
| `stop <app>` | `docker compose stop` (the-gibson docker apps only) |

Typical flow: edit + push (step 1) → `sudo -u zero-cool …/hermes-broker deploy <app>`.
It streams the Ansible run and prints SUCCESS or FAILURE.

## Notes & boundaries

- **Adding a NEW service**: create its `compose/<svc>/`, `ansible/roles/<svc>/`,
  `ansible/playbooks/<svc>.yml`, its `ports:` entry and `caddy_services` entry
  in `vars.yml`, commit + push, then `deploy <svc>` (and `deploy caddy` +
  `deploy pihole` so the new subdomain routes + resolves).
- **Denylisted (won't deploy — run these by hand)**: `storage` (formats drives)
  and `bootstrap` (re-bases the OS). Everything else in the repo is fair game.
- **pi5 services** (caddy, pihole, wireguard, stremio, …): `deploy` works;
  `restart`/`stop`/`logs` don't (no local compose file) — use `deploy`.
- **Deploying `hermes` (yourself)** restarts your own services — the current
  session drops, but the deploy finishes in its own unit; reconnect and
  `status` to confirm.
- **Secrets**: values in the Ansible vault are edited with `make edit-vault`
  (needs the vault password, which you don't hold — ask a human for vault
  changes). Non-secret config you can edit + push yourself.
- Only `hermes-broker` is permitted via sudo; any other `sudo` is denied.
