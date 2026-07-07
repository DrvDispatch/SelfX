# SelfX on a VPS (short version — full walkthrough in docs/REPORT.md)

Prerequisites: a VPS with Docker Engine + the compose plugin, and a domain you control.

## 1. DNS

Create an `A` (and optionally `AAAA`) record for your domain pointing at the VPS IP,
e.g. `selfx.example.com → 203.0.113.10`. Wait until it resolves before starting the
proxy — Caddy needs it for the Let's Encrypt challenge.

## 2. Clone + harden .env

```bash
git clone <your-repo-url> selfx && cd selfx
cp .env.example .env
```

Edit `.env` — at minimum:

- `SELFX_SECRET_KEY` — long random value: `openssl rand -hex 32`
- `SELFX_ADMIN_PASSWORD` — strong bootstrap admin password
- `POSTGRES_PASSWORD` — random value, and mirror it inside `DATABASE_URL`
- `SELFX_DOMAIN` — the domain from step 1 (e.g. `selfx.example.com`)

## 3. Start with the TLS proxy

```bash
docker compose --profile proxy up -d --build
# add more profiles as needed, e.g.:
docker compose --profile proxy --profile ai --profile security up -d --build
```

Caddy publishes 80/443, obtains a certificate automatically, and proxies to `web:80`.
Browse to `https://<SELFX_DOMAIN>` and log in with the bootstrap admin.

## 4. Firewall

Allow only SSH + HTTP(S):

```bash
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
```

Note: Docker publishes ports via iptables directly, so ufw does NOT block them.
The core `web` service publishes `8080:80`; on a public VPS either leave it (harmless
but redundant next to Caddy) or bind it to loopback by changing the mapping in
`docker-compose.yml` to `"127.0.0.1:8080:80"`. `stirling` (`extras` profile,
`8081:8080`) has no auth of its own — bind it to loopback too if you enable it.
