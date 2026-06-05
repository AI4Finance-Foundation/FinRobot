#!/usr/bin/env bash
# Cut a FinRobot desktop release and publish it to the public "releases" repo.
#
# Path A (closed source, public binary distribution): the source repo stays
# private; only the compiled .dmg + the Tauri updater artifacts are published to
# a separate PUBLIC GitHub repo, from whose latest Release the app's in-app
# updater reads latest.json (endpoint configured in src-tauri/tauri.conf.json).
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
RELEASES_REPO="${RELEASES_REPO:-lrz68/finrobot-releases}"
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

echo "[release] version=$VERSION  triple=$TRIPLE  repo=$RELEASES_REPO  dry-run=$DRY_RUN"

# ── 1. Sync the version into tauri.conf.json (drives getVersion + updater compare)
node -e '
  const fs = require("fs");
  const f = process.argv[1], v = process.argv[2];
  const o = JSON.parse(fs.readFileSync(f, "utf8"));
  o.version = v;
  fs.writeFileSync(f, JSON.stringify(o, null, 2) + "\n");
' "$CONF" "$VERSION"
echo "[release] set tauri.conf.json version → $VERSION"

# ── 2. (Optional) refreeze the Python sidecar for this arch ───────────────────
if [[ "$BUILD_SIDECAR" == 1 ]]; then
    echo "[release] rebuilding sidecar…"
    "$SRC_TAURI/sidecar/build.sh"
fi
if [[ ! -f "$SRC_TAURI/binaries/finrobot-server-$TRIPLE" ]]; then
    echo >&2 "ERROR: sidecar binaries/finrobot-server-$TRIPLE missing — run with --build-sidecar"
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
DL_BASE="https://github.com/$RELEASES_REPO/releases/download/v$VERSION"

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
PREV_MIN="$(curl -fsSL "https://github.com/$RELEASES_REPO/releases/latest/download/min-version.json" 2>/dev/null \
    | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{process.stdout.write(String(JSON.parse(s).min_version||"0.0.0"))}catch{process.stdout.write("0.0.0")}})' \
    || echo "0.0.0")"
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
echo "[release] creating release v$VERSION on $RELEASES_REPO…"
gh release create "v$VERSION" \
    --repo "$RELEASES_REPO" \
    --title "FinRobot v$VERSION" \
    --notes "${NOTES:-FinRobot v$VERSION}" \
    "$DMG" "$APP_TARBALL" "$APP_SIG" "$LATEST_JSON" "$MIN_JSON"

echo "[release] done. Installed apps will see v$VERSION on their next launch check."
