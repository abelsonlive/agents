---
name: homelab-deploy
description: |
  Deploy, restart, and inspect homelab services (home.abelson.live) from the
  the-gibson host via the bounded deploy broker. Use when asked to deploy an
  app, roll out a change, restart or stop a service, check what's running, or
  read a service's logs. Only apps in the deploy catalog can be acted on; the
  broker refuses anything else.
license: ISC
---

# Homelab deploy

You (Hermes) run bare-metal on **the-gibson** and drive homelab deploys through
a single allowlisted command — the **deploy broker**. You do **not** have direct
docker, Ansible, SSH, or vault access; the broker holds those and validates
every request. You cannot widen your own authority.

## The one command

```
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker <verb> [app] [tag]
```

| verb | what it does | scope |
|---|---|---|
| `list` | print the deployable app catalog | — |
| `status [app]` | `docker compose ps` (all, or one app) | the-gibson |
| `logs <app> [lines]` | tail a service's container logs (default 100) | the-gibson docker apps |
| `deploy <app> [tag]` | re-run the app's Ansible playbook (canonical deploy from origin/main) | whole fleet |
| `restart <app>` | `docker compose restart` | the-gibson docker apps |
| `stop <app>` | `docker compose stop` | the-gibson docker apps |

## How to use it

1. **Always `list` first** if unsure whether an app is deployable — the broker
   rejects anything not in the catalog, so guessing wastes a turn.
2. **`deploy` is the canonical way to roll out a change.** It fast-forwards the
   deploy checkout to `origin/main` and re-runs the playbook, so make sure the
   change is committed and pushed to `main` first — `deploy` never picks up
   uncommitted or unpushed work. It streams the Ansible run and reports SUCCESS
   or FAILURE at the end.
3. `restart`/`stop`/`logs` only work for docker apps on the-gibson. For pi5
   services (caddy, pihole, wireguard, stremio, …) use `deploy`.
4. **Deploying `hermes` (yourself)** works, but it restarts your own services —
   the current chat/session will drop. The deploy itself finishes in the
   background (its own systemd unit); confirm afterwards with a fresh `status`.
5. On failure the broker prints the transient unit name; you can read more with
   `sudo -u zero-cool journalctl -u <unit>` — but do **not** try other sudo
   commands: only `hermes-broker` is permitted, everything else is denied.

## Examples

```
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker list
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker status
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker logs immich 200
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker deploy n8n
sudo -u zero-cool /usr/local/lib/hermes/hermes-broker restart navidrome
```

## Boundaries (do not fight these)

- Only catalog apps; only these verbs; only via `sudo -u zero-cool`.
- You cannot read the vault password, the deploy SSH key, or `/etc/hermes/*`,
  and cannot write the deploy checkout at `/srv/homelab`. That is intentional.
- To make an app deployable that isn't in `list`, ask a human to add it to
  `hermes_deploy_catalog` (roles/hermes_deploy_broker) — you cannot self-grant.
