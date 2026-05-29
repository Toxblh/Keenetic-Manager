#!/usr/bin/env bash
# test-isolated.sh - Verify KeeneticManager.app runs without Homebrew or system Python
set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/KeeneticManager.app"
DMG="${DMG_PATH:-}"
BREW="${HOMEBREW_PREFIX:-/opt/homebrew}"
APP_NAME="KeeneticManager"
APP_ID="ru.toxblh.KeeneticManager"
SMOKE_SECONDS="${SMOKE_SECONDS:-8}"
TERM_VALUE="${TERM:-xterm-256color}"
TMPDIR_VALUE="${TMPDIR:-/tmp}"

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run scripts/bundle-macos.sh first." >&2
    exit 1
fi

if [ -z "$DMG" ]; then
    DMG="$(find dist -maxdepth 1 -name 'KeeneticManager-*.dmg' -type f -print 2>/dev/null \
        | sort | tail -1)"
fi

echo "==> KeeneticManager isolation test"
echo "    App:  $APP"
echo "    DMG:  ${DMG:-missing}"
echo "    Brew: $BREW"

indent() {
    while IFS= read -r line; do
        echo "    $line"
    done
}

fail_with_log() {
    local message="$1"
    local log_file="${2:-}"
    echo ""
    echo "FAIL: $message"
    if [ -n "$log_file" ] && [ -f "$log_file" ]; then
        echo "---- log: $log_file ----"
        sed -n '1,220p' "$log_file" | indent
        echo "---- end log ----"
    fi
    exit 1
}

cleanup_pid() {
    local pid="${1:-}"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null && return 0 || true
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || return 0
            sleep 1
        done
        kill -9 "$pid" 2>/dev/null || true
    fi
}

find_app_pids() {
    local app_path="$1"
    pgrep -f "$app_path/Contents/Resources/launch.py" 2>/dev/null || true
    pgrep -f "$app_path/Contents/MacOS/keeneticmanager" 2>/dev/null || true
}

wait_for_pid_from_app_path() {
    local app_path="$1"
    local pid=""
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        pid="$(find_app_pids "$app_path" | awk 'NF {print; exit}')"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        sleep 1
    done
    return 1
}

make_pixbuf_cache() {
    local resources="$1"
    local template="$resources/gdk-pixbuf/loaders.cache"
    local cache
    cache="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-pixbuf-cache)"

    if grep -q "@RESOURCES@" "$template" 2>/dev/null; then
        sed "s|@RESOURCES@|$resources|g" "$template" > "$cache"
    else
        cp "$template" "$cache"
    fi

    echo "$cache"
}

run_for_smoke_window() {
    local pid="$1"
    local seconds="$2"
    local log_file="$3"
    local label="$4"

    for _ in $(seq 1 "$seconds"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            local exit_code=0
            wait "$pid" 2>/dev/null || exit_code=$?
            fail_with_log "$label exited before the smoke window (exit code $exit_code)" "$log_file"
        fi
        sleep 1
    done
}

run_webp_decode_probe() {
    local app_path="$1"
    local label="$2"
    local launcher="$app_path/Contents/MacOS/keeneticmanager"
    local dir bundle resources frameworks py_ver py_fw py_bin py_sitepackages pixbuf_cache log exit_code

    dir="$(cd "$(dirname "$launcher")" && pwd)"
    bundle="$(dirname "$dir")"
    resources="$bundle/Resources"
    frameworks="$bundle/Frameworks"
    py_ver="$(find "$frameworks/Python.framework/Versions" -maxdepth 1 -mindepth 1 -type d -name '3.*' | head -1 | xargs -I{} /usr/bin/basename {})"
    py_fw="$frameworks/Python.framework/Versions/$py_ver"
    py_bin="$py_fw/bin/python$py_ver"
    py_sitepackages="$py_fw/lib/python$py_ver/site-packages"
    pixbuf_cache="$(make_pixbuf_cache "$resources")"
    log="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-webp-probe)"

    set +e
    env -i \
        HOME="$HOME" \
        TMPDIR="$TMPDIR_VALUE" \
        TERM="$TERM_VALUE" \
        PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
        DYLD_FRAMEWORK_PATH="$frameworks" \
        DYLD_LIBRARY_PATH="$frameworks" \
        PYTHONHOME="$py_fw" \
        PYTHONPATH="$resources/app:$py_sitepackages" \
        GI_TYPELIB_PATH="$resources/girepository-1.0" \
        GSETTINGS_SCHEMA_DIR="$resources/glib-2.0/schemas" \
        GDK_PIXBUF_MODULE_FILE="$pixbuf_cache" \
        "$py_bin" -c "
import base64, os, tempfile
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
payload = base64.b64decode('UklGRj4AAABXRUJQVlA4IDIAAAAQAgCdASoBAAEAAgA0JaACdLoB+AH6AAPIAP784yX/0AZLaqL/0Aj/9AGS2qi/8+oAAA==')
fd, path = tempfile.mkstemp(suffix='.webp')
try:
    os.write(fd, payload)
    os.close(fd)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    assert pixbuf.get_width() == 1 and pixbuf.get_height() == 1
    print('WebP decode: OK')
finally:
    if not os.path.exists(path):
        pass
    else:
        os.unlink(path)
" >"$log" 2>&1
    exit_code=$?
    set -e

    if [ "$exit_code" -ne 0 ]; then
        fail_with_log "$label WebP decode failed (exit code $exit_code)" "$log"
    fi

    sed -n '1,40p' "$log" | indent
}

cleanup_keyring_entry() {
    env -i \
        HOME="$HOME" \
        TMPDIR="$TMPDIR_VALUE" \
        TERM="$TERM_VALUE" \
        PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
        DYLD_FRAMEWORK_PATH="$FRAMEWORKS" \
        DYLD_LIBRARY_PATH="$FRAMEWORKS" \
        PYTHONHOME="$PY_FW" \
        PYTHONPATH="$RESOURCES/app:$PY_SITEPACKAGES" \
        GI_TYPELIB_PATH="$RESOURCES/girepository-1.0" \
        GSETTINGS_SCHEMA_DIR="$RESOURCES/glib-2.0/schemas" \
        GDK_PIXBUF_MODULE_FILE="$PIXBUF_CACHE" \
        "$PY_BIN" -c "import keyring; keyring.delete_password('keeneticmanager-isolation-test', 'test')" \
        >/dev/null 2>&1 || true
}

# ── 1. Check for Homebrew leaks in dylibs ──────────────────────────────────────
echo ""
echo "-- Checking dylib install names..."
LEAKS=$(find "$APP" -type f \( -name "*.dylib" -o -name "*.so" \) \
    -exec sh -c 'otool -L "$1" 2>/dev/null | tail -n +3 | grep -q "$2" && echo "$1"' _ {} "$BREW" \; 2>/dev/null)
if [ -n "$LEAKS" ]; then
    echo "FAIL: Found Homebrew path leaks:"
    echo "$LEAKS" | while IFS= read -r f; do echo "  $f"; done
    exit 1
fi
echo "PASS: No Homebrew path leaks"

# ── 1b. Check all required typelibs are present in the bundle ─────────────────
echo ""
echo "-- Checking required typelibs..."
TL_DIR="$APP/Contents/Resources/girepository-1.0"
TL_FAIL=0
for tl in Adw-1 Gdk-4.0 GdkMacos-4.0 GdkPixbuf-2.0 GdkPixdata-2.0 \
          Gio-2.0 GLib-2.0 GModule-2.0 GObject-2.0 \
          Graphene-1.0 Gsk-4.0 Gtk-4.0 \
          HarfBuzz-0.0 cairo-1.0 fontconfig-2.0 freetype2-2.0 \
          Pango-1.0 PangoCairo-1.0 PangoFc-1.0 PangoFT2-1.0; do
    if [ ! -f "$TL_DIR/$tl.typelib" ]; then
        echo "  MISSING: $tl.typelib"
        TL_FAIL=1
    fi
done
if [ "$TL_FAIL" -eq 1 ]; then
    echo "FAIL: Missing typelibs listed above"
    exit 1
fi
echo "PASS: All required typelibs present"

# ── 2. Verify key bundle files exist ──────────────────────────────────────────
echo ""
echo "-- Checking bundle structure..."
for required in \
    "$APP/Contents/MacOS/keeneticmanager" \
    "$APP/Contents/Resources/launch.py" \
    "$APP/Contents/Info.plist" \
    "$APP/Contents/Resources/girepository-1.0" \
    "$APP/Contents/Resources/glib-2.0/schemas" \
    "$APP/Contents/Resources/icons" \
    "$APP/Contents/Resources/app"; do
    if [ ! -e "$required" ]; then
        echo "FAIL: Missing $required"
        exit 1
    fi
done
echo "PASS: Bundle structure OK"

# ── 3. Test Python imports and keyring in isolation ───────────────────────────
echo ""
echo "-- Testing Python imports + keyring (isolated env)..."

LAUNCHER="$APP/Contents/MacOS/keeneticmanager"
DIR="$(cd "$(dirname "$LAUNCHER")" && pwd)"
BUNDLE="$(dirname "$DIR")"
RESOURCES="$BUNDLE/Resources"
FRAMEWORKS="$BUNDLE/Frameworks"
PY_VER=$(find "$FRAMEWORKS/Python.framework/Versions" -maxdepth 1 -mindepth 1 -type d -name '3.*' | head -1 | xargs -I{} /usr/bin/basename {})
PY_FW="$FRAMEWORKS/Python.framework/Versions/$PY_VER"
PY_BIN="$PY_FW/bin/python$PY_VER"
PY_SITEPACKAGES="$PY_FW/lib/python$PY_VER/site-packages"
PIXBUF_CACHE="$(make_pixbuf_cache "$RESOURCES")"

echo "    Python: $PY_BIN"

IMPORT_LOG="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-import)"
set +e
env -i \
    HOME="$HOME" \
    TMPDIR="$TMPDIR_VALUE" \
    TERM="$TERM_VALUE" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    DYLD_FRAMEWORK_PATH="$FRAMEWORKS" \
    DYLD_LIBRARY_PATH="$FRAMEWORKS" \
    PYTHONHOME="$PY_FW" \
    PYTHONPATH="$RESOURCES/app:$PY_SITEPACKAGES" \
    GI_TYPELIB_PATH="$RESOURCES/girepository-1.0" \
    GSETTINGS_SCHEMA_DIR="$RESOURCES/glib-2.0/schemas" \
    GDK_PIXBUF_MODULE_FILE="$PIXBUF_CACHE" \
    "$PY_BIN" -c "
import sys, gettext
sys.path.insert(0, '$RESOURCES/app')
gettext.bindtextdomain('keeneticmanager', '$RESOURCES/locale')
gettext.textdomain('keeneticmanager')
gettext.install('keeneticmanager', '$RESOURCES/locale')
import gi
from gi.repository import Gio
gresource = Gio.Resource.load('$RESOURCES/app/keeneticmanager.gresource')
gresource._register()
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
print('Python:', sys.version)
print('GTK4+Adwaita: OK')
import keyring
backend = keyring.get_keyring().__class__
backend_name = backend.__module__ + '.' + backend.__name__
print('keyring:', backend_name)
if 'keyring.backends.macOS' not in backend.__module__:
    raise RuntimeError('Expected macOS keyring backend, got ' + backend_name)
keyring.set_password('keeneticmanager-isolation-test', 'test', 'hello')
assert keyring.get_password('keeneticmanager-isolation-test', 'test') == 'hello'
keyring.delete_password('keeneticmanager-isolation-test', 'test')
print('keyring Keychain: read/write/delete OK')
import keeneticmanager.main
print('keeneticmanager.main: OK')
import base64, os, tempfile
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf
payload = base64.b64decode('UklGRj4AAABXRUJQVlA4IDIAAAAQAgCdASoBAAEAAgA0JaACdLoB+AH6AAPIAP784yX/0AZLaqL/0Aj/9AGS2qi/8+oAAA==')
fd, path = tempfile.mkstemp(suffix='.webp')
try:
    os.write(fd, payload)
    os.close(fd)
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    assert pixbuf.get_width() == 1 and pixbuf.get_height() == 1
finally:
    if os.path.exists(path):
        os.unlink(path)
print('WebP decode: OK')
print('ALL_CHECKS_PASSED')
" >"$IMPORT_LOG" 2>&1
IMPORT_EXIT=$?
set -e

sed -n '1,220p' "$IMPORT_LOG" | indent
cleanup_keyring_entry

if [ "$IMPORT_EXIT" -ne 0 ]; then
    fail_with_log "Import/keyring test failed (exit code $IMPORT_EXIT)" "$IMPORT_LOG"
fi

if ! grep -q "ALL_CHECKS_PASSED" "$IMPORT_LOG"; then
    fail_with_log "Import/keyring test did not complete" "$IMPORT_LOG"
fi
echo "PASS: Python imports and keyring OK"

# ── 4. Launch the bundled app executable in a minimal environment ─────────────
echo ""
echo "-- Testing .app launcher startup (isolated env)..."

LAUNCH_LOG="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-launcher)"
set +e
env -i \
    HOME="$HOME" \
    TMPDIR="$TMPDIR_VALUE" \
    TERM="$TERM_VALUE" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    "$LAUNCHER" >"$LAUNCH_LOG" 2>&1 &
LAUNCH_PID=$!
set -e

run_for_smoke_window "$LAUNCH_PID" "$SMOKE_SECONDS" "$LAUNCH_LOG" "Bundled launcher"
cleanup_pid "$LAUNCH_PID"
wait "$LAUNCH_PID" 2>/dev/null || true

if [ -s "$LAUNCH_LOG" ]; then
    sed -n '1,160p' "$LAUNCH_LOG" | indent
fi
echo "PASS: Bundled launcher stayed alive for ${SMOKE_SECONDS}s"

# ── 5. Launch the app from the DMG with macOS open ────────────────────────────
echo ""
echo "-- Testing DMG/open startup..."

if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
    echo "FAIL: DMG not found. Expected dist/KeeneticManager-*.dmg or DMG_PATH=/path/to/file.dmg"
    exit 1
fi

ATTACH_LOG="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-dmg-attach)"
set +e
hdiutil attach -nobrowse -readonly "$DMG" >"$ATTACH_LOG" 2>&1
ATTACH_EXIT=$?
set -e

if [ "$ATTACH_EXIT" -ne 0 ]; then
    fail_with_log "Failed to mount DMG (exit code $ATTACH_EXIT)" "$ATTACH_LOG"
fi

MOUNT_POINT="$(awk '/\/Volumes\// {print substr($0, index($0, "/Volumes/"))}' "$ATTACH_LOG" | tail -1)"
if [ -z "$MOUNT_POINT" ] || [ ! -d "$MOUNT_POINT" ]; then
    fail_with_log "DMG mounted, but mount point was not detected" "$ATTACH_LOG"
fi

DMG_PID=""
cleanup_dmg() {
    cleanup_pid "$DMG_PID"
    if [ -n "$MOUNT_POINT" ]; then
        hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true
    fi
}
trap cleanup_dmg EXIT

MOUNTED_APP="$MOUNT_POINT/$APP_NAME.app"
if [ ! -d "$MOUNTED_APP" ]; then
    fail_with_log "Mounted DMG does not contain $APP_NAME.app" "$ATTACH_LOG"
fi

echo "    Mounted WebP decode probe:"
run_webp_decode_probe "$MOUNTED_APP" "Mounted DMG app"

OPEN_LOG="$(TMPDIR="$TMPDIR_VALUE" mktemp -t keeneticmanager-open)"
set +e
/usr/bin/open -n "$MOUNTED_APP" >"$OPEN_LOG" 2>&1
OPEN_EXIT=$?
set -e

if [ "$OPEN_EXIT" -ne 0 ]; then
    fail_with_log "open failed for mounted app (exit code $OPEN_EXIT)" "$OPEN_LOG"
fi

if ! DMG_PID="$(wait_for_pid_from_app_path "$MOUNTED_APP")"; then
    fail_with_log "Could not find a running KeeneticManager process from mounted DMG" "$OPEN_LOG"
fi

run_for_smoke_window "$DMG_PID" "$SMOKE_SECONDS" "$OPEN_LOG" "Mounted DMG app"
cleanup_dmg
trap - EXIT

echo "PASS: DMG app stayed alive for ${SMOKE_SECONDS}s"

# ── 6. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  PASSED: App is self-contained and ready for distribution."
echo "══════════════════════════════════════════"
