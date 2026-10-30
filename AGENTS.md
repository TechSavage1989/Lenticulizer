# AGENTS.md

## Read this first

This repository is the intended long-term home for Lenticulizer.

Before changing code, releases, build files, repository layout, or updater behavior:

1. Read this file.
2. Read `DEVELOPMENT_HANDOFF.md`.
3. Inspect the latest `main`, active branches, open pull requests, releases, and workflow status.
4. Confirm the current source/build baseline before editing.
5. Do not substitute an older archive when newer confirmed source exists.

## Current repository state

As of 2026-10-30, the repository was created with only a minimal README and had:

- one branch: `main`;
- no GitHub releases;
- no pull requests;
- no published application source;
- no production GitHub update feed.

The latest confirmed pre-repository functional baseline is documented in `docs/releases/alpha31-baseline.md`.

Do not claim that GitHub is authoritative for binaries, source, or updates until the migration is completed and validated.

## Ownership and publication

Repository: `TechSavage1989/Lenticulizer`

Visibility at bootstrap: public.

Do not:

- change repository visibility;
- publish application source unless the approved source-publication scope is explicit;
- publish binaries or releases without release authorization;
- create or embed credentials/tokens;
- overwrite an existing release/tag.

Documentation-only maintenance may proceed without incrementing the application version.

## Target application behavior

- Windows-first portable/self-contained app.
- Stable executable filename for shortcuts and updater replacement.
- Mutable state belongs in per-user app storage, not beside the executable.
- Retain only one previous rollback backup.
- Preserve settings across updates.
- Clean only app-owned staging/temp data after the new app is visibly healthy.

## Updater requirements

When updater work begins, implement and validate all of the following:

- startup check without blocking slow diagnostics;
- checks every five minutes while active/online;
- focus-return check when at least two minutes have elapsed;
- correctly bound native-window timers;
- single-flight requests;
- conditional requests / ETags;
- shared-IP unauthenticated API-rate-limit handling;
- `Retry-After` and backoff;
- manual-check cooldowns;
- no false “up to date” state on offline/error responses;
- explicit Download and Install and restart actions;
- no automatic download or restart;
- active-operation restart guard;
- trusted HTTPS repository/asset allowlist;
- expected cryptographic hashes;
- archive traversal / decompression-bomb / unexpected-executable rejection;
- app-identity and version checks, including Windows PE checks;
- safe staging and rollback;
- visible healthy-window confirmation before success.

A matching hash alone is not publisher signing.

## Testing expectations

For updater and packaging changes, test the real experience, not only mocked clocks:

- startup;
- native/browser timers;
- focus return;
- offline and error behavior;
- throttling;
- cleanup;
- settings preservation;
- rollback;
- previous-version → new-release download;
- digest verification;
- staging;
- install;
- relaunch.

Use a negative control when fixing a reproducible defect.

Disclose any Windows, WebView2, Blender, printing, or other target-platform validation that was not actually performed.

## Repository organization

Preferred structure once source migration is authorized:

- `README.md`
- `AGENTS.md`
- `DEVELOPMENT_HANDOFF.md`
- required build/package manifests and small build-entry wrappers
- `.github/`
- `src/` or the existing toolchain-appropriate implementation structure
- `tests/`
- `scripts/`
- `assets/`
- `docs/`
- `docs/releases/`
- `vendor/` only for required vendored dependencies/assets

Do not accumulate binaries, source ZIPs, logs, temporary reports, or obsolete handoffs in the tracked root.

Before moving files, map every path dependency: builds, CI, embeds, resources, tests, package manifests, scripts, docs, and image references.

## Root guard

A tracked-root allowlist and CI root-layout guard are required when source migration is performed.

The guard must:

- work in a normal Git checkout;
- also work from an extracted source archive without `.git`;
- explicitly exclude generated build outputs;
- fail on an unapproved tracked/root file;
- pass on a clean tree.

Demonstrate both the negative and clean controls without committing deliberate clutter.

## README standard

Keep `README.md` user-first and concise, with these section names/order when applicable:

1. Features
2. Download
3. Requirements
4. Getting started
5. How to use
6. Updates and settings
7. Troubleshooting
8. Development
9. License — only when a repository license is verified

Use the existing authentic icon/logo only when a valid repository asset exists. Do not invent branding or fabricate screenshots.

## Release handoff

Before calling a release ready:

- verify the exact commit/tag;
- verify hosted CI;
- verify downloadable assets;
- verify hashes;
- verify release/update-feed behavior;
- update README as needed;
- update `DEVELOPMENT_HANDOFF.md`;
- record release notes in `docs/releases/`;
- ensure source/test/build assets are complete within the approved publication scope;
- state remaining validation limitations explicitly.
