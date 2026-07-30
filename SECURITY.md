# Security policy

## Supported versions

This repository is a reference implementation. Security fixes are applied to
the latest revision; no long-term support branches are promised yet.

## Reporting a vulnerability

Do not open a public issue with an exploit, private source, credentials, tokens,
internal hostnames, or backup archives.

Report privately to the repository owner/security contact configured for the
deployment. Include:

- affected commit/image digest and component;
- minimal reproduction using synthetic data;
- impact and required attacker access;
- whether credentials or private repositories may be exposed;
- suggested mitigation, if known.

If this project is published on a forge with private security advisories, use
that mechanism. Deployment owners should define a monitored security address
before exposing the service beyond localhost.

## Immediate response

If a Git/OpenAI/OIDC/backup secret may have leaked:

1. revoke or rotate it first;
2. stop the exposed endpoint or narrow the firewall;
3. preserve sanitized logs and IDs;
4. inspect Wiki, proposals, backups and clients for propagation;
5. restore from a verified backup if integrity is uncertain.

## Deployment assumptions

The safe default is one trusted user on localhost. Authentication, TLS and
multi-tenant authorization are required before a shared deployment.

Repository contents, LLM output, Markdown and MCP input are untrusted. Do not
run analyzed repositories on the host. Keep Codex credentials outside all
containers and project data.

See `docs/10-security.md` for the threat model and hardening checklist.
