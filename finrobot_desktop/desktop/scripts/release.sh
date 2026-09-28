#!/usr/bin/env bash
# Cut a FinRobot desktop release and publish it to the public MAIN repo.
#
# Path A (closed source, public binary distribution): the source repo stays
# private; only the compiled .dmg + the Tauri updater artifacts are published as
# a Release on the org's public flagship repo (AI4Finance-Foundation/FinRobot),
# from whose latest Release the app's in-app updater reads latest.json
# (endpoint configured in src-tauri/tauri.conf.json). Downloads and stars stay
# unified on one repo (leader's call, 2026-07-07; the separate finrobot-releases
# repo was retired the same day).
#
# ⚠️ The updater reads `releases/latest` of this SHARED repo. Desktop releases
# are tagged desktop-vX.Y.Z (the bare vX.Y.Z line belongs to the legacy
# project). Any future NON-desktop release on the main repo MUST be marked
# "pre-release", or it will shadow `releases/latest` and silently blind every
# installed app. The post-publish guard at the bottom catches this at release
# time.
#
# We build LOCALLY (this Mac already has the toolchain + the frozen sidecar)
# rather than in CI, so a release costs $0 and burns no private-repo macOS
# Action minutes. Switch to CI later only if you outgrow the manual loop.
#
# Usage:
#   ./scripts/release.sh 1.2.0 "Fixed DCF rounding; added dark theme."
#   ./scripts/release.sh 1.2.0 --notes-file CHANGELOG_1.2.0.md
#   ./scripts/release.sh 1.2.0 "notes" --dry-run     # build + manifests, NO upload
#   ./scripts/release.sh 1.2.0 "notes" --mandatory   # FORCE: hard-block every older install
#
# --mandatory raises the min-version floor to this version: on next check, every
# app below 1.2.0 shows a full-screen non-dismissible gate until it updates.
# Normal releases carry the existing floor forward (stay optional).
#
# Prereqs (one-time):
#   • RELEASES_REPO below points at your public releases repo (owner/name).
#   • The updater public key in src-tauri/tauri.conf.json matches the private
#     key referenced by TAURI_SIGNING_PRIVATE_KEY (default ~/.tauri/finrobot-updater.key).
#   • `gh auth login` done, with push access to RELEASES_REPO.
#   • Sidecar built for this arch (scripts/build runs sidecar/build.sh) — pass
#     --build-sidecar to (re)freeze it as part of the release.
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
# The PUBLIC repo that hosts releases. MUST match the owner baked into
# src-tauri/tauri.conf.json → plugins.updater.endpoints. Override via env.
RELEASES_REPO="${RELEASES_REPO:-AI4Finance-Foundation/FinRobot}"
# Private key that signs the update bundle (Tauri reads the file path or its
# contents). Generated once via `npm run tauri -- signer generate`.
: "${TAURI_SIGNING_PRIVATE_KEY:=$HOME/.tauri/finrobot-updater.key}"
: "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:=}"   # empty — key was generated with --ci

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # desktop/scripts
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"                  # desktop
SRC_TAURI="$DESKTOP_DIR/src-tauri"
CONF="$SRC_TAURI/tauri.conf.json"
BUNDLE_DIR="$SRC_TAURI/target/release/bundle"

# ── Args ─────────────────────────────────────────────────────────────────────
VERSION="${1:-}"
if [[ -z "$VERSION" || ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo >&2 "ERROR: first arg must be a semver, e.g. ./scripts/release.sh 1.2.0"
    exit 1
fi
shift
NOTES=""
DRY_RUN=0
BUILD_SIDECAR=0
MANDATORY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --build-sidecar) BUILD_SIDECAR=1; shift ;;
        --mandatory) MANDATORY=1; shift ;;
        --notes-file) NOTES="$(cat "$2")"; shift 2 ;;
        *) NOTES="$1"; shift ;;
    esac
done

# ── Preflight ────────────────────────────────────────────────────────────────
if [[ "$RELEASES_REPO" == __GH_OWNER__/* ]]; then
    echo >&2 "ERROR: set RELEASES_REPO (and the matching owner in tauri.conf.json) first."
    exit 1
fi
if [[ ! -f "$TAURI_SIGNING_PRIVATE_KEY" && ! "$TAURI_SIGNING_PRIVATE_KEY" == *"untrusted comment"* ]]; then
    echo >&2 "ERROR: signing key not found at $TAURI_SIGNING_PRIVATE_KEY"
    echo >&2 "       generate it: cd desktop && npm run tauri -- signer generate -w ~/.tauri/finrobot-updater.key"
    exit 1
fi
command -v rustc >/dev/null || { echo >&2 "ERROR: rustc not found"; exit 1; }
[[ "$DRY_RUN" == 1 ]] || command -v gh >/dev/null || { echo >&2 "ERROR: gh CLI not found"; exit 1; }

# Map the Rust host triple → Tauri updater platform key.
TRIPLE="$(rustc -Vv | sed -n 's/^host: //p')"
case "$TRIPLE" in
    aarch64-apple-darwin) PLATFORM_KEY="darwin-aarch64" ;;
    x86_64-apple-darwin)  PLATFORM_KEY="darwin-x86_64" ;;
    *) echo >&2 "ERROR: unsupported host triple $TRIPLE (this script targets macOS)"; exit 1 ;;
esac

# Desktop releases live on the shared main repo under their own tag line —
# desktop-vX.Y.Z — because the bare vX.Y.Z line is already taken by the legacy
# project (v1.0.0 "Equity Research") and the two must never collide.
TAG="desktop-v$VERSION"

echo "[release] version=$VERSION  tag=$TAG  triple=$TRIPLE  repo=$RELEASES_REPO  dry-run=$DRY_RUN"

# ── 0. Release quality gate — RED ABORTS. No skip flag; runs even under --dry-run ─
# Mirrors CI (.github/workflows/ci.yml) plus the pytest blocks each write session
# runs locally. Serial by design: the pytest concurrency guard forbids two runs in
# one rootdir, and a release must never race itself. This is the whole point of
# gating HERE — before any version file is mutated or minutes are spent building —
# so a red gate costs nothing and a green one is the release's audit record.
# Python tools go through `uv run` so the gate works whether or not a venv is
# activated (identical to CI); integration tests are auto-skipped by the
# `-m 'not integration'` default in pyproject.toml (they hit the live network).
REPO_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
_gate_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
_gate_run() {   # _gate_run "<label>" "<workdir>" <cmd> [args...]
    local label="$1" workdir="$2"; shift 2
    echo "[gate $(_gate_ts)] > $label"
    if ! ( cd "$workdir" && "$@" ); then
        echo >&2 ""
        echo >&2 "[gate $(_gate_ts)] FAILED -- $label"
        echo >&2 "[gate] RELEASE ABORTED: fix the failure above. A red gate never ships."
        exit 1
    fi
    echo "[gate $(_gate_ts)] PASS -- $label"
}

echo "[gate $(_gate_ts)] ===== release quality gate: START (target v$VERSION) ====="
# Backend (from repo root)
_gate_run "ruff check finrobot/"                        "$REPO_ROOT" uv run ruff check finrobot/
_gate_run "mypy finrobot/ --strict"                     "$REPO_ROOT" uv run mypy finrobot/ --strict
_gate_run "pytest tests/unit"                           "$REPO_ROOT" uv run pytest tests/unit -q
_gate_run "pytest routes+audit+artifact+engine+events"  "$REPO_ROOT" uv run pytest tests/routes tests/audit tests/artifact tests/engine tests/test_events.py -q
# Frontend (from desktop/)
_gate_run "npm run lint"          "$DESKTOP_DIR" npm run lint
_gate_run "npm run format:check"  "$DESKTOP_DIR" npm run format:check
_gate_run "npm test"              "$DESKTOP_DIR" npm test
_gate_run "npm run build"         "$DESKTOP_DIR" npm run build
echo "[gate $(_gate_ts)] ===== release quality gate: PASSED ====="

# ── 1. Stamp $VERSION into all four version sources (single source of truth) ──
# tauri.conf.json drives getVersion() + the updater's version compare; the other
# three keep the app / npm / cargo / python package metadata in lockstep so
# nothing ever reports a stale version. Every file gets a SURGICAL line edit that
# touches only its version string — NOT a parse-and-rewrite. (node JSON.stringify
# / jq would reformat tauri.conf.json's hand-compacted inline objects into a
# 30-line noise diff on every release; a targeted sed keeps the formatting.) The
# top-level JSON "version" is uniquely at 2-space indent; the TOML version is
# scoped to the [package] / [project] section so a dependency pin is never hit.
# --dry-run prints the diff for all four and writes nothing.
PKG_JSON="$DESKTOP_DIR/package.json"
CARGO_TOML="$SRC_TAURI/Cargo.toml"
PYPROJECT="$REPO_ROOT/pyproject.toml"

_stamp_json() {   # replace only the top-level "version" line (2-space indent) → stdout
    sed -e "s/^  \"version\": \"[^\"]*\"/  \"version\": \"$VERSION\"/" "$1"
}
_stamp_toml() {   # replace the version line inside a named [section] via sed → stdout
    sed -e "/^\[$2\]/,/^\[/ s/^version = \".*\"/version = \"$VERSION\"/" "$1"
}
_apply_version() {   # _apply_version <label> <file> <newcontent-cmd...>
    local label="$1" file="$2"; shift 2
    local tmp; tmp="$(mktemp)"
    "$@" > "$tmp"
    if diff -u "$file" "$tmp" >/dev/null 2>&1; then
        echo "[release] version $label: already $VERSION (no change)"
    else
        echo "[release] version $label → $VERSION:"
        # `|| true`: diff exits 1 when files differ, which under set -o pipefail
        # would abort the release mid-preview. The diff here is purely cosmetic.
        diff -u "$file" "$tmp" | tail -n +3 | sed 's/^/    /' || true
    fi
    if [[ "$DRY_RUN" == 1 ]]; then rm -f "$tmp"; else mv "$tmp" "$file"; fi
}

_apply_version "tauri.conf.json" "$CONF"       _stamp_json "$CONF"
_apply_version "package.json"    "$PKG_JSON"   _stamp_json "$PKG_JSON"
_apply_version "Cargo.toml"      "$CARGO_TOML" _stamp_toml "$CARGO_TOML" package
_apply_version "pyproject.toml"  "$PYPROJECT"  _stamp_toml "$PYPROJECT" project
echo "[release] stamped version → $VERSION across 4 files (dry-run=$DRY_RUN)"

# ── 2. (Optional) refreeze the Python sidecar for this arch ───────────────────
if [[ "$BUILD_SIDECAR" == 1 ]]; then
    echo "[release] rebuilding sidecar…"
    "$SRC_TAURI/sidecar/build.sh"
fi
if [[ ! -x "$SRC_TAURI/sidecar/dist/finrobot-server/finrobot-server" ]]; then
    echo >&2 "ERROR: sidecar one-dir bundle missing at sidecar/dist/finrobot-server/ — run with --build-sidecar"
    exit 1
fi

# ── 3. Build + sign the app (produces .dmg + .app.tar.gz + .app.tar.gz.sig) ───
echo "[release] building signed bundle (this takes a few minutes)…"
export TAURI_SIGNING_PRIVATE_KEY TAURI_SIGNING_PRIVATE_KEY_PASSWORD
( cd "$DESKTOP_DIR" && npm run tauri -- build )

# ── 4. Locate artifacts ──────────────────────────────────────────────────────
APP_TARBALL="$(ls "$BUNDLE_DIR"/macos/*.app.tar.gz 2>/dev/null | head -1 || true)"
APP_SIG="$(ls "$BUNDLE_DIR"/macos/*.app.tar.gz.sig 2>/dev/null | head -1 || true)"
DMG="$(ls "$BUNDLE_DIR"/dmg/*.dmg 2>/dev/null | head -1 || true)"
for f in "$APP_TARBALL" "$APP_SIG" "$DMG"; do
    [[ -f "$f" ]] || { echo >&2 "ERROR: expected build artifact missing (got '$f')"; exit 1; }
done
SIGNATURE="$(cat "$APP_SIG")"
TARBALL_NAME="$(basename "$APP_TARBALL")"
PUB_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DL_BASE="https://github.com/$RELEASES_REPO/releases/download/$TAG"

# ── 5. Generate latest.json (the manifest the in-app updater polls) ───────────
LATEST_JSON="$BUNDLE_DIR/latest.json"
node -e '
  const fs = require("fs");
  const [out, version, notes, pubDate, platformKey, url, signature] = process.argv.slice(1);
  const manifest = {
    version,
    notes,
    pub_date: pubDate,
    platforms: { [platformKey]: { signature, url } },
  };
  fs.writeFileSync(out, JSON.stringify(manifest, null, 2) + "\n");
' "$LATEST_JSON" "$VERSION" "$NOTES" "$PUB_DATE" "$PLATFORM_KEY" "$DL_BASE/$TARBALL_NAME" "$SIGNATURE"
echo "[release] wrote $LATEST_JSON"

# ── 5b. min-version.json (forced-update floor) ────────────────────────────────
# Every release carries this file so the app can always read it from
# releases/latest. Normal release → carry the existing floor forward; a
# --mandatory release → raise the floor to THIS version, so every older install
# is hard-blocked until it updates. The previous floor is read from the
# currently-published file (default 0.0.0 on the very first release).
# `|| true` (NOT `|| echo "0.0.0"`): the node reader already emits "0.0.0" for a
# missing/unparseable manifest, and set -o pipefail makes the curl failure fail
# the whole pipeline — so `|| echo` would fire IN ADDITION to node's output and
# concatenate into "0.0.00.0.0" (a malformed floor on the very first release).
# The `[[ -z ]]` line below is the real empty-guard.
PREV_MIN="$(curl -fsSL "https://github.com/$RELEASES_REPO/releases/latest/download/min-version.json" 2>/dev/null \
    | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(s).min_version||"0.0.0"))}catch{process.stdout.write("0.0.0")}})' \
    || true)"
[[ -z "$PREV_MIN" ]] && PREV_MIN="0.0.0"
if [[ "$MANDATORY" == 1 ]]; then MIN_VERSION="$VERSION"; else MIN_VERSION="$PREV_MIN"; fi
MIN_JSON="$BUNDLE_DIR/min-version.json"
node -e '
  const fs = require("fs");
  fs.writeFileSync(process.argv[1], JSON.stringify({ min_version: process.argv[2] }, null, 2) + "\n");
' "$MIN_JSON" "$MIN_VERSION"
echo "[release] min-version floor = $MIN_VERSION (prev=$PREV_MIN, mandatory=$MANDATORY)"

if [[ "$DRY_RUN" == 1 ]]; then
    echo "[release] DRY RUN — artifacts ready, NOT uploading. Inspect:"
    echo "          $DMG"
    echo "          $APP_TARBALL"
    echo "          $LATEST_JSON"
    echo "          $MIN_JSON"
    exit 0
fi

# ── 6. Publish the GitHub Release on the PUBLIC repo ──────────────────────────
# ${...} braces are load-bearing: a bare $RELEASES_REPO followed by a multibyte
# char (the … here) makes macOS bash fold the UTF-8 bytes into the variable name
# → "RELEASES_REPO…: unbound variable" under set -u. Never butt a non-ASCII char
# directly against a brace-less expansion in this script.
echo "[release] creating release $TAG on ${RELEASES_REPO}…"
gh release create "$TAG" \
    --repo "$RELEASES_REPO" \
    --latest \
    --title "FinRobot Desktop v$VERSION" \
    --notes "${NOTES:-FinRobot Desktop v$VERSION}" \
    "$DMG" "$APP_TARBALL" "$APP_SIG" "$LATEST_JSON" "$MIN_JSON"

# ── 7. Post-publish guard: is the updater endpoint actually serving us? ───────
# The updater polls `releases/latest` of the SHARED main repo. If another
# (non-desktop) release ever shadows "latest", or propagation lags, installed
# apps go silently blind. Assert the live manifest serves exactly this version.
LIVE=""
for _ in 1 2 3 4 5; do
    LIVE="$(curl -fsSL "https://github.com/$RELEASES_REPO/releases/latest/download/latest.json" 2>/dev/null \
        | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(s).version||""))}catch{}})' \
        || true)"
    [[ "$LIVE" == "$VERSION" ]] && break
    sleep 5
done
if [[ "$LIVE" != "$VERSION" ]]; then
    echo >&2 "ERROR: updater endpoint serves '${LIVE:-nothing}' (expected $VERSION)."
    echo >&2 "       releases/latest on $RELEASES_REPO is shadowed by another release"
    echo >&2 "       (mark non-desktop releases as pre-release) or has not propagated."
    exit 1
fi
echo "[release] updater endpoint verified: releases/latest serves v$VERSION"

echo "[release] done. Installed apps will see v$VERSION on their next launch check."
