#!/usr/bin/env bash
# bundle-macos.sh - Creates a self-contained KeeneticManager.app for macOS distribution
set -euo pipefail
cd "$(dirname "$0")/.."

BREW="${HOMEBREW_PREFIX:-/opt/homebrew}"

# Auto-detect the highest installed Homebrew Python 3.x
PY_VER="${PYTHON_VERSION:-}"
if [ -z "$PY_VER" ]; then
    PY_VER="$(find "$BREW/Cellar" -maxdepth 1 -name 'python@3.*' -type d \
        | sed 's|.*/python@||' | sort -t. -k1,1n -k2,2n | tail -1)"
fi
if [ -z "$PY_VER" ]; then
    echo "ERROR: No Homebrew python@3.x found. Install with: brew install python@3.12" >&2
    exit 1
fi

APP_VERSION="$(grep "version:" meson.build | head -1 | grep -oE "[0-9]+\.[0-9]+\.[0-9]+")"
APP_NAME="KeeneticManager"
APP_ID="ru.toxblh.KeeneticManager"
DIST_DIR="dist"

# Find Python framework
PY_CELLAR="$(find "$BREW/Cellar/python@$PY_VER" -maxdepth 1 -mindepth 1 -type d | head -1)"
PY_FW_SRC="$PY_CELLAR/Frameworks/Python.framework"
PY_ROOT="$PY_FW_SRC/Versions/$PY_VER"

APP="$DIST_DIR/$APP_NAME.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
FRAMEWORKS="$CONTENTS/Frameworks"

echo "==> KeeneticManager $APP_VERSION macOS bundle"
echo "    Python: $PY_ROOT"

# ── 1. Clean & create structure ──────────────────────────────────────────────
# chmod first in case a previous run left a locked signed framework
chmod -R u+w "$DIST_DIR" 2>/dev/null || true
rm -rf "$DIST_DIR"
mkdir -p "$MACOS" "$RESOURCES" "$FRAMEWORKS"

# ── 2. Build the app ─────────────────────────────────────────────────────────
echo "==> Building app (release)..."
if [ -d "_build" ]; then
    PATH="$BREW/bin:$PATH" command meson configure _build \
        -Dprefix="$(pwd)/_build/testdir" \
        -Dbuildtype=release 2>/dev/null || true
else
    PATH="$BREW/bin:$PATH" command meson setup _build \
        --prefix="$(pwd)/_build/testdir" \
        --buildtype=release
fi
PATH="$BREW/bin:$PATH" ninja -C _build install

# ── 3. Copy app data ─────────────────────────────────────────────────────────
echo "==> Copying app data..."
cp -r _build/testdir/share/keeneticmanager/. "$RESOURCES/app/"
mkdir -p "$RESOURCES/locale" "$RESOURCES/glib-2.0"
cp -r _build/testdir/share/locale/. "$RESOURCES/locale/" 2>/dev/null || true
cp -r _build/testdir/share/glib-2.0/schemas "$RESOURCES/glib-2.0/"
# Copy GTK4's own settings schemas (needed for correct GTK4/Adwaita theming)
for schema in "$BREW/share/glib-2.0/schemas/org.gtk.gtk4.Settings"*.xml; do
    [ -f "$schema" ] && cp "$schema" "$RESOURCES/glib-2.0/schemas/"
done
"$BREW/bin/glib-compile-schemas" "$RESOURCES/glib-2.0/schemas/"

# ── 4. Copy icons ─────────────────────────────────────────────────────────────
echo "==> Copying icons..."
mkdir -p "$RESOURCES/icons/hicolor/scalable/apps"

# App icon (SVG)
cp "data/icons/hicolor/scalable/apps/$APP_ID.svg" \
   "$RESOURCES/icons/hicolor/scalable/apps/"

# Adwaita theme — only symbolic icons (much smaller than full theme)
ADWAITA_SRC="$BREW/share/icons/Adwaita"
mkdir -p "$RESOURCES/icons/Adwaita"
if [ -d "$ADWAITA_SRC/symbolic" ]; then
    cp -r "$ADWAITA_SRC/symbolic" "$RESOURCES/icons/Adwaita/"
elif [ -d "$ADWAITA_SRC/scalable" ]; then
    cp -r "$ADWAITA_SRC/scalable" "$RESOURCES/icons/Adwaita/"
fi
cp "$ADWAITA_SRC/index.theme" "$RESOURCES/icons/Adwaita/" 2>/dev/null || true

# Hicolor index
cp "$BREW/share/icons/hicolor/index.theme" "$RESOURCES/icons/hicolor/" 2>/dev/null || true

# Update icon caches
"$BREW/bin/gtk4-update-icon-cache" -q -t -f "$RESOURCES/icons/hicolor" 2>/dev/null || true

# ── 5. Bundle Python.framework ───────────────────────────────────────────────
echo "==> Bundling Python.framework (~67MB, please wait)..."
# Use tar to exclude _CodeSignature — macOS protects signed frameworks during copy,
# blocking all subsequent writes once _CodeSignature lands in the destination
mkdir -p "$FRAMEWORKS/Python.framework"
(
    cd "$(dirname "$PY_FW_SRC")"
    tar cf - \
        --exclude='Python.framework/_CodeSignature' \
        --exclude='Python.framework/Versions/*/_CodeSignature' \
        "$(basename "$PY_FW_SRC")"
) | tar xf - -C "$FRAMEWORKS/"
BUNDLED_PY_FW="$FRAMEWORKS/Python.framework"
BUNDLED_PY="$BUNDLED_PY_FW/Versions/$PY_VER"
chmod -R u+w "$BUNDLED_PY_FW/"

# ── 5b. Patch Python.app so Dock/Activity Monitor show our name, not "Python" ─
echo "==> Patching Python.app identity..."
PYTHON_APP_PLIST="$BUNDLED_PY/Resources/Python.app/Contents/Info.plist"
if [ -f "$PYTHON_APP_PLIST" ]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $APP_ID"              "$PYTHON_APP_PLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleName Keenetic Manager"           "$PYTHON_APP_PLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PYTHON_APP_PLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION"            "$PYTHON_APP_PLIST"
    /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Keenetic Manager" "$PYTHON_APP_PLIST" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Keenetic Manager" "$PYTHON_APP_PLIST"
    echo "   Python.app identity patched"
else
    echo "   WARNING: Python.app/Info.plist not found, skipping"
fi

# Remove unnecessary bulk
rm -rf "$BUNDLED_PY/include"
rm -rf "$BUNDLED_PY/share"
find "$BUNDLED_PY/lib/python$PY_VER" -name "*.pyc" -delete 2>/dev/null || true
find "$BUNDLED_PY/lib/python$PY_VER" \( -name "test" -o -name "tests" \) \
    -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUNDLED_PY/lib/python$PY_VER" -name "__pycache__" \
    -type d -exec rm -rf {} + 2>/dev/null || true

# site-packages inside the framework is a symlink to the Homebrew system dir — replace with real dir
PY_SITEPACKAGES="$BUNDLED_PY/lib/python$PY_VER/site-packages"
SYS_SITEPACKAGES="$BREW/lib/python$PY_VER/site-packages"
if [ -L "$PY_SITEPACKAGES" ]; then
    rm "$PY_SITEPACKAGES"
    mkdir "$PY_SITEPACKAGES"
fi

echo "==> Adding Python packages (gi, cairo, requests, netifaces, keyring)..."
for pkg in gi cairo; do
    [ -d "$SYS_SITEPACKAGES/$pkg" ] && cp -r "$SYS_SITEPACKAGES/$pkg" "$PY_SITEPACKAGES/"
done
# Remove GStreamer overrides — they reference GStreamer dylibs not bundled here
find "$PY_SITEPACKAGES/gi" -name "*gst*" -delete 2>/dev/null || true

# Add pure-Python packages (requests, keyring and their deps) — directory-based
for pkg in requests keyring urllib3 certifi charset_normalizer idna \
           jaraco more_itertools; do
    [ -d "$SYS_SITEPACKAGES/$pkg" ] && cp -r "$SYS_SITEPACKAGES/$pkg" "$PY_SITEPACKAGES/" 2>/dev/null || true
done
# Add C-extension single-file packages (e.g. netifaces installs as a .so, not a dir)
find "$SYS_SITEPACKAGES" -maxdepth 1 -name "netifaces*.so" \
    -exec cp {} "$PY_SITEPACKAGES/" \; 2>/dev/null || true
# Also copy .dist-info so importlib.metadata works
find "$SYS_SITEPACKAGES" -maxdepth 1 -name "*.dist-info" -exec cp -r {} "$PY_SITEPACKAGES/" \; 2>/dev/null || true

# ── 6. Copy GObject typelibs ─────────────────────────────────────────────────
echo "==> Copying typelibs..."
mkdir -p "$RESOURCES/girepository-1.0"
for tl in Adw-1 Gdk-4.0 GdkMacos-4.0 GdkPixbuf-2.0 GdkPixdata-2.0 \
          Gio-2.0 GioUnix-2.0 GLib-2.0 GLibUnix-2.0 GModule-2.0 GObject-2.0 \
          Graphene-1.0 Gsk-4.0 Gtk-4.0 \
          HarfBuzz-0.0 cairo-1.0 fontconfig-2.0 freetype2-2.0 \
          Pango-1.0 PangoCairo-1.0 PangoFc-1.0 PangoFT2-1.0 PangoOT-1.0; do
    src="$BREW/lib/girepository-1.0/$tl.typelib"
    [ -f "$src" ] && cp "$src" "$RESOURCES/girepository-1.0/"
done

# ── 7. Copy GTK4 + deps dylibs ───────────────────────────────────────────────
echo "==> Copying GTK4 dylibs..."
copy_dylib() {
    local pkg="$1"   # e.g. "gtk4"
    local stem="$2"  # e.g. "libgtk-4" (no version, no .dylib)
    local found=""
    # Build search list from existing dirs only (find exits 1 on missing paths)
    local dirs=("$BREW/lib")
    [ -d "$BREW/opt/$pkg/lib" ] && dirs=("$BREW/opt/$pkg/lib" "${dirs[@]}")
    found="$(find "${dirs[@]}" -maxdepth 1 -name "${stem}*.dylib" 2>/dev/null \
        | sort -V | tail -1)" || true
    if [ -n "$found" ]; then
        cp -n "$found" "$FRAMEWORKS/" 2>/dev/null || true
    else
        echo "  WARNING: not found: $pkg/$stem"
    fi
}

copy_dylib "gtk4"        "libgtk-4"
copy_dylib "libadwaita"  "libadwaita-1"
copy_dylib "glib"        "libglib-2.0"
copy_dylib "glib"        "libgobject-2.0"
copy_dylib "glib"        "libgio-2.0"
copy_dylib "glib"        "libgmodule-2.0"
copy_dylib "glib"        "libgirepository-2.0"
copy_dylib "pango"       "libpango-1.0"
copy_dylib "pango"       "libpangocairo-1.0"
copy_dylib "pango"       "libpangoft2-1.0"
copy_dylib "cairo"       "libcairo.2"
copy_dylib "cairo"       "libcairo-gobject.2"
copy_dylib "cairo"       "libcairo-script-interpreter"
copy_dylib "harfbuzz"    "libharfbuzz.0"
copy_dylib "harfbuzz"    "libharfbuzz-subset"
copy_dylib "fribidi"     "libfribidi"
copy_dylib "gdk-pixbuf"  "libgdk_pixbuf-2.0"
copy_dylib "libepoxy"    "libepoxy"
copy_dylib "graphene"    "libgraphene-1.0"
copy_dylib "fontconfig"  "libfontconfig"
copy_dylib "freetype"    "libfreetype"
copy_dylib "gettext"     "libintl"
copy_dylib "appstream"   "libappstream"
copy_dylib "libpng"      "libpng16"
copy_dylib "jpeg-turbo"  "libjpeg"
copy_dylib "libtiff"     "libtiff"
copy_dylib "webp"        "libwebp.7"
copy_dylib "webp"        "libwebpdemux"
copy_dylib "pcre2"       "libpcre2-8"
copy_dylib "lzo"         "liblzo2"
copy_dylib "pixman"      "libpixman-1"
copy_dylib "brotli"      "libbrotlidec"
copy_dylib "brotli"      "libbrotlicommon"
# Transitive deps not pulled in by the above
copy_dylib "graphite2"   "libgraphite2.3"
copy_dylib "libthai"     "libthai.0"
copy_dylib "libdatrie"   "libdatrie.1"
copy_dylib "libxmlb"     "libxmlb.2"
copy_dylib "libfyaml"    "libfyaml.0"
copy_dylib "zstd"        "libzstd.1"
copy_dylib "xz"          "liblzma.5"
copy_dylib "openssl@3"   "libcrypto.3"
copy_dylib "openssl@3"   "libssl.3"
copy_dylib "mpdecimal"   "libmpdec.4"
copy_dylib "sqlite"      "libsqlite3"
copy_dylib "webp"        "libwebpmux.3"

# Use dylibbundler to recursively collect any remaining transitive deps
echo "==> Running dylibbundler (collecting transitive dependencies)..."
SEARCH_FLAGS=(
    -s "$BREW/lib"
    -s "$BREW/opt/gtk4/lib"
    -s "$BREW/opt/libadwaita/lib"
    -s "$BREW/opt/glib/lib"
    -s "$BREW/opt/pango/lib"
    -s "$BREW/opt/cairo/lib"
    -s "$BREW/opt/harfbuzz/lib"
    -s "$BREW/opt/gdk-pixbuf/lib"
    -s "$BREW/opt/fontconfig/lib"
    -s "$BREW/opt/freetype/lib"
    -s "$BREW/opt/gettext/lib"
    -s "$BREW/opt/graphene/lib"
    -s "$BREW/opt/libepoxy/lib"
    -s "$BREW/opt/fribidi/lib"
    -s "$BREW/opt/libpng/lib"
    -s "$BREW/opt/jpeg-turbo/lib"
    -s "$BREW/opt/libtiff/lib"
    -s "$BREW/opt/appstream/lib"
    -s "$BREW/opt/pcre2/lib"
    -s "$BREW/opt/lzo/lib"
    -s "$BREW/opt/pixman/lib"
    -s "$BREW/opt/brotli/lib"
    -s "$BREW/opt/webp/lib"
    -s "$BREW/opt/graphite2/lib"
    -s "$BREW/opt/libthai/lib"
    -s "$BREW/opt/libdatrie/lib"
    -s "$BREW/opt/libxmlb/lib"
    -s "$BREW/opt/libfyaml/lib"
    -s "$BREW/opt/zstd/lib"
    -s "$BREW/opt/xz/lib"
    -s "$BREW/opt/openssl@3/lib"
    -s "$BREW/opt/mpdecimal/lib"
    -s "$BREW/opt/sqlite/lib"
    -i /usr/lib
    -i /System
)

# Fix .so extension modules (gi, cairo, netifaces)
SO_FILES=()
for so in "$PY_SITEPACKAGES/gi/_gi.cpython"*".so" \
          "$PY_SITEPACKAGES/gi/_gi_cairo.cpython"*".so" \
          "$PY_SITEPACKAGES/cairo/_cairo.cpython"*".so" \
          "$PY_SITEPACKAGES/netifaces"*".so"; do
    [ -f "$so" ] && SO_FILES+=(-x "$so")
done

dylibbundler -b -of \
    -x "$BUNDLED_PY/bin/python$PY_VER" \
    ${SO_FILES[@]+"${SO_FILES[@]}"} \
    -d "$FRAMEWORKS/" \
    -p "@executable_path/../Frameworks/" \
    "${SEARCH_FLAGS[@]}" 2>/dev/null || true

# ── 8. gdk-pixbuf loaders ────────────────────────────────────────────────────
echo "==> Copying pixbuf loaders..."
PIXBUF_SRC="$BREW/lib/gdk-pixbuf-2.0/2.10.0/loaders"
PIXBUF_DEST="$RESOURCES/gdk-pixbuf/2.10.0/loaders"
mkdir -p "$PIXBUF_DEST"
# Use -L to dereference symlinks (e.g. libpixbufloader-webp.so is a Homebrew symlink)
find "$PIXBUF_SRC" \( -name "*.so" -o -name "*.dylib" \) | while IFS= read -r f; do
    cp -L "$f" "$PIXBUF_DEST/"
done 2>/dev/null || true

# Generate loaders.cache from the HOMEBREW source loaders BEFORE install_name_tool rewrites,
# so gdk-pixbuf-query-loaders can actually load them (they still have Homebrew paths).
# Then replace the Homebrew loaders path with @RESOURCES@ placeholder.
LOADERS_CACHE="$RESOURCES/gdk-pixbuf/loaders.cache"
"$BREW/bin/gdk-pixbuf-query-loaders" "$PIXBUF_SRC/"*.so > "$LOADERS_CACHE" 2>/dev/null || true
sed -i '' "s|$PIXBUF_SRC|@RESOURCES@/gdk-pixbuf/2.10.0/loaders|g" "$LOADERS_CACHE" 2>/dev/null || true

# ── 8.5 Rewrite all Homebrew install names → @executable_path/../Frameworks/ ──
# dylibbundler rewrites refs inside Python/.so but does NOT rewrite the install
# names of the dylibs themselves. This step fixes that for every binary in the
# bundle, handling versioned-name mismatches (e.g. libjpeg.8.dylib → libjpeg.8.3.2.dylib).
echo "==> Rewriting Homebrew paths in bundle binaries..."

# Pre-compute ref_name→actual_name mapping into a temp file.
# ref_name  = basename of the install name (what other dylibs call this lib)
# actual_name = filename on disk in Frameworks/
_MAPPING=$(mktemp -t km-dylib-map)
for _lib in "$FRAMEWORKS/"*.dylib; do
    [ -f "$_lib" ] || continue
    _actual=$(basename "$_lib")
    _iname=$(otool -D "$_lib" 2>/dev/null | awk 'NR==2{print $0}')
    _ibase="${_iname##*/}"
    # actual→actual (direct match)
    printf '%s %s\n' "$_actual" "$_actual" >> "$_MAPPING"
    # install-name-basename→actual (handles libfoo.7.dylib → libfoo.7.2.0.dylib)
    [ "$_ibase" != "$_actual" ] && printf '%s %s\n' "$_ibase" "$_actual" >> "$_MAPPING"
done

_fix_binary() {
    local file="$1"
    chmod u+w "$file" 2>/dev/null || true
    # Fix each Homebrew dep that has a bundled counterpart
    while IFS= read -r dep; do
        local ref="${dep##*/}"
        local actual
        actual=$(grep "^${ref} " "$_MAPPING" | awk '{print $2}' | head -1 || true)
        if [ -n "$actual" ]; then
            install_name_tool -change "$dep" \
                "@executable_path/../Frameworks/$actual" "$file" 2>/dev/null || true
        fi
    done < <(otool -L "$file" 2>/dev/null | awk 'NR>1 {print $1}' \
             | grep -E '^/opt/(homebrew|local)' || true)
    # Fix own install name to use actual filename (for dylibs)
    local self_id actual_name
    self_id=$(otool -D "$file" 2>/dev/null | awk 'NR==2{print $0}')
    actual_name=$(basename "$file")
    case "$self_id" in
        /opt/*|@executable_path/*)
            install_name_tool -id \
                "@executable_path/../Frameworks/$actual_name" "$file" 2>/dev/null || true ;;
    esac
}

# Fix Frameworks dylibs
for _lib in "$FRAMEWORKS/"*.dylib; do
    [ -f "$_lib" ] && _fix_binary "$_lib"
done
# Fix Python extension modules
find "$BUNDLED_PY/lib/python$PY_VER/site-packages" \
     "$BUNDLED_PY/lib/python$PY_VER/lib-dynload" \
     -name "*.so" 2>/dev/null | while IFS= read -r _so; do
    _fix_binary "$_so"
done
# Fix pixbuf loaders
for _so in "$PIXBUF_DEST/"*.so "$PIXBUF_DEST/"*.dylib; do
    [ -f "$_so" ] && _fix_binary "$_so"
done

rm -f "$_MAPPING"
echo "   Done"

# ── 9. Create Python launch script ───────────────────────────────────────────
echo "==> Creating Python launcher..."
cat > "$RESOURCES/launch.py" << PYEOF
import os, sys, signal, gettext

# Set process name before any GUI framework init so Dock/Activity Monitor show our name
if sys.platform == 'darwin':
    try:
        from Foundation import NSProcessInfo
        NSProcessInfo.processInfo().setProcessName_('Keenetic Manager')
    except Exception:
        pass

# Resolve bundle paths
_macos = os.path.dirname(os.path.abspath(__file__))  # Contents/MacOS
_bundle = os.path.dirname(_macos)                     # Contents
_resources = os.path.join(_bundle, "Resources")

pkgdatadir = os.path.join(_resources, "app")
localedir  = os.path.join(_resources, "locale")

sys.path.insert(1, pkgdatadir)
signal.signal(signal.SIGINT, signal.SIG_DFL)
gettext.bindtextdomain("keeneticmanager", localedir)
gettext.install("keeneticmanager", localedir)

import gi
from gi.repository import Gio
gresource = os.path.join(pkgdatadir, "keeneticmanager.gresource")
Gio.Resource.load(gresource)._register()

from keeneticmanager import main
sys.exit(main.main("$APP_VERSION"))
PYEOF

# ── 10. Create shell launcher ─────────────────────────────────────────────────
echo "==> Creating shell launcher..."
cat > "$MACOS/keeneticmanager" << LAUNCHER_EOF
#!/usr/bin/env bash
DIR="\$(cd "\$(dirname "\$0")" && pwd)"
BUNDLE="\$(dirname "\$DIR")"
RESOURCES="\$BUNDLE/Resources"
FRAMEWORKS="\$BUNDLE/Frameworks"
PY_FW="\$FRAMEWORKS/Python.framework/Versions/$PY_VER"
PY_BIN="\$PY_FW/bin/python$PY_VER"

# Build a temp loaders.cache with resolved paths; original stays as @RESOURCES@ template
# so the file is never modified in place (required for read-only DMG mounts)
_LOADERS_TEMPLATE="\$RESOURCES/gdk-pixbuf/loaders.cache"
_LOADERS_CACHE="\$(mktemp -t keeneticmanager-pixbuf)"
if grep -q "@RESOURCES@" "\$_LOADERS_TEMPLATE" 2>/dev/null; then
    sed "s|@RESOURCES@|\$RESOURCES|g" "\$_LOADERS_TEMPLATE" > "\$_LOADERS_CACHE"
else
    cp "\$_LOADERS_TEMPLATE" "\$_LOADERS_CACHE"
fi

export DYLD_FRAMEWORK_PATH="\$FRAMEWORKS"
export DYLD_LIBRARY_PATH="\$FRAMEWORKS:\${DYLD_LIBRARY_PATH:-}"
export PYTHONHOME="\$PY_FW"
export PYTHONPATH="\$PY_FW/lib/python$PY_VER/site-packages"
export GI_TYPELIB_PATH="\$RESOURCES/girepository-1.0"
export GSETTINGS_SCHEMA_DIR="\$RESOURCES/glib-2.0/schemas"
export XDG_DATA_DIRS="\$RESOURCES"
export GDK_PIXBUF_MODULE_FILE="\$_LOADERS_CACHE"

# Prevent GTK from looking for GSettings schemas system-wide
export DCONF_PROFILE=/dev/null

exec "\$PY_BIN" "\$RESOURCES/launch.py" "\$@"
LAUNCHER_EOF
chmod +x "$MACOS/keeneticmanager"

# ── 11. Create Info.plist ─────────────────────────────────────────────────────
echo "==> Creating Info.plist..."
cat > "$CONTENTS/Info.plist" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>       <string>keeneticmanager</string>
  <key>CFBundleIdentifier</key>       <string>$APP_ID</string>
  <key>CFBundleName</key>             <string>Keenetic Manager</string>
  <key>CFBundleDisplayName</key>      <string>Keenetic Manager</string>
  <key>CFBundleVersion</key>          <string>$APP_VERSION</string>
  <key>CFBundleShortVersionString</key><string>$APP_VERSION</string>
  <key>CFBundleIconFile</key>         <string>keeneticmanager</string>
  <key>CFBundlePackageType</key>      <string>APPL</string>
  <key>LSMinimumSystemVersion</key>   <string>13.0</string>
  <key>NSHighResolutionCapable</key>  <true/>
  <key>NSRequiresAquaSystemAppearance</key><false/>
  <key>NSHumanReadableCopyright</key> <string>Copyright © 2024 toxblh. MIT License.</string>
</dict>
</plist>
PLIST_EOF

printf "APPL????" > "$CONTENTS/PkgInfo"

# ── 12. Create ICNS icon ──────────────────────────────────────────────────────
echo "==> Creating ICNS icon..."
SVG_SRC="data/icons/hicolor/scalable/apps/$APP_ID.svg"
ICONSET_DIR="$RESOURCES/keeneticmanager.iconset"
mkdir -p "$ICONSET_DIR"

for size in 16 32 64 128 256 512; do
    rsvg-convert -w "$size" -h "$size" "$SVG_SRC" \
        > "$ICONSET_DIR/icon_${size}x${size}.png" 2>/dev/null || true
    dbl=$((size * 2))
    [ $size -le 256 ] && rsvg-convert -w "$dbl" -h "$dbl" "$SVG_SRC" \
        > "$ICONSET_DIR/icon_${size}x${size}@2x.png" 2>/dev/null || true
done

iconutil -c icns -o "$RESOURCES/keeneticmanager.icns" "$ICONSET_DIR" 2>/dev/null \
    && echo "   ICNS created" || echo "   WARNING: iconutil failed, icon will be missing"
rm -rf "$ICONSET_DIR"

# Replace Python.app default icon with ours (keep same filename — iconservices caches by name)
PYTHON_APP_RES="$BUNDLED_PY/Resources/Python.app/Contents/Resources"
if [ -f "$RESOURCES/keeneticmanager.icns" ] && [ -d "$PYTHON_APP_RES" ]; then
    cp "$RESOURCES/keeneticmanager.icns" "$PYTHON_APP_RES/PythonInterpreter.icns" 2>/dev/null || true
    cp "$RESOURCES/keeneticmanager.icns" "$PYTHON_APP_RES/PythonApplet.icns"      2>/dev/null || true
    echo "   Python.app icon replaced"
fi

# ── 13. Ad-hoc code sign ─────────────────────────────────────────────────────
# Ad-hoc signing allows Privacy & Security → "Open Anyway" to work.
# Without a real Developer ID the app still won't pass Gatekeeper automatically,
# but macOS will show "Open Anyway" instead of a hard block.
echo "==> Ad-hoc signing..."
# Sign all dylibs and .so files first (inside-out order required by codesign)
find "$FRAMEWORKS" "$CONTENTS" \
    \( -name "*.dylib" -o -name "*.so" \) \
    -exec codesign --force --sign - {} \; 2>/dev/null || true
# Sign the Python binary
codesign --force --sign - "$BUNDLED_PY/bin/python$PY_VER" 2>/dev/null || true
# Sign the whole .app bundle last
codesign --force --deep --sign - "$APP" 2>/dev/null \
    && echo "   Signed (ad-hoc)" || echo "   WARNING: codesign failed"

# Re-sign Python.app explicitly — patching Info.plist invalidated its signature
PYTHON_APP_MACOS="$BUNDLED_PY/Resources/Python.app/Contents/MacOS/Python"
PYTHON_APP_PATH="$BUNDLED_PY/Resources/Python.app"
codesign --force --sign - "$PYTHON_APP_MACOS" 2>/dev/null || true
codesign --force --sign - "$PYTHON_APP_PATH"  2>/dev/null || true

# Override iconservices cache by writing the icon via NSWorkspace extended attribute.
# This is the only reliable way to replace the icon without a reboot/cache flush.
# Uses Homebrew Python which has PyObjC; falls back silently if unavailable.
echo "==> Setting custom icon via NSWorkspace..."
"$BREW/bin/python3" - "$RESOURCES/keeneticmanager.icns" "$PYTHON_APP_PATH" <<'PYEOF' || true
import sys
try:
    from AppKit import NSWorkspace, NSImage
    icon_path, app_path = sys.argv[1], sys.argv[2]
    img = NSImage.alloc().initWithContentsOfFile_(icon_path)
    if img:
        ok = NSWorkspace.sharedWorkspace().setIcon_forFile_options_(img, app_path, 0)
        print("   Custom icon set: " + ("OK" if ok else "FAILED"))
    else:
        print("   WARNING: failed to load icon file")
except Exception as e:
    print("   WARNING: NSWorkspace icon step skipped: " + str(e))
PYEOF

# ── 14. Bundle size summary ───────────────────────────────────────────────────
echo ""
echo "==> Bundle summary:"
du -sh "$FRAMEWORKS" "$RESOURCES" "$MACOS"
echo "Total:"
du -sh "$APP"

# ── 15. Create DMG ───────────────────────────────────────────────────────────
echo ""
echo "==> Creating DMG..."
DMG_NAME="$APP_NAME-$APP_VERSION.dmg"
rm -f "$DIST_DIR/$DMG_NAME"

hdiutil create \
    -volname "Keenetic Manager" \
    -srcfolder "$APP" \
    -ov -format UDZO \
    "$DIST_DIR/$DMG_NAME"

echo ""
echo "══════════════════════════════════════════"
echo "  Done!"
echo "  App:  $APP"
echo "  DMG:  $DIST_DIR/$DMG_NAME"
echo "══════════════════════════════════════════"
