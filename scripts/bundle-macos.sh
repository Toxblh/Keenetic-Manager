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
PATH="$BREW/bin:$PATH" command meson configure _build \
    -Dprefix="$(pwd)/_build/testdir" \
    -Dbuildtype=release 2>/dev/null || true
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

# Add pure-Python packages (requests, netifaces, keyring and their deps)
for pkg in requests netifaces keyring urllib3 certifi charset_normalizer idna \
           jaraco more_itertools; do
    [ -d "$SYS_SITEPACKAGES/$pkg" ] && cp -r "$SYS_SITEPACKAGES/$pkg" "$PY_SITEPACKAGES/" 2>/dev/null || true
done
# Also copy .dist-info so importlib.metadata works
find "$SYS_SITEPACKAGES" -maxdepth 1 -name "*.dist-info" -exec cp -r {} "$PY_SITEPACKAGES/" \; 2>/dev/null || true

# ── 6. Copy GObject typelibs ─────────────────────────────────────────────────
echo "==> Copying typelibs..."
mkdir -p "$RESOURCES/girepository-1.0"
for tl in Adw-1 Gdk-4.0 GdkMacos-4.0 GdkPixbuf-2.0 GdkPixdata-2.0 \
          Gio-2.0 GioUnix-2.0 GLib-2.0 GLibUnix-2.0 GObject-2.0 \
          Gsk-4.0 Gtk-4.0 Pango-1.0 PangoCairo-1.0 PangoFc-1.0 PangoFT2-1.0; do
    src="$BREW/lib/girepository-1.0/$tl.typelib"
    [ -f "$src" ] && cp "$src" "$RESOURCES/girepository-1.0/"
done

# ── 7. Copy GTK4 + deps dylibs ───────────────────────────────────────────────
echo "==> Copying GTK4 dylibs..."
copy_dylib() {
    local rel="$1"
    local src
    # Try opt/ path first, then lib/
    src="$BREW/opt/$rel"
    [ ! -f "$src" ] && src="$BREW/lib/$(basename "$rel")"
    if [ -f "$src" ]; then
        cp -n "$src" "$FRAMEWORKS/" 2>/dev/null || true
        return 0
    fi
    echo "  WARNING: not found: $rel"
}

copy_dylib "gtk4/lib/libgtk-4.1.dylib"
copy_dylib "libadwaita/lib/libadwaita-1.0.dylib"
copy_dylib "glib/lib/libglib-2.0.0.dylib"
copy_dylib "glib/lib/libgobject-2.0.0.dylib"
copy_dylib "glib/lib/libgio-2.0.0.dylib"
copy_dylib "glib/lib/libgmodule-2.0.0.dylib"
copy_dylib "glib/lib/libgirepository-2.0.0.dylib"
copy_dylib "pango/lib/libpango-1.0.0.dylib"
copy_dylib "pango/lib/libpangocairo-1.0.0.dylib"
copy_dylib "pango/lib/libpangoft2-1.0.0.dylib"
copy_dylib "cairo/lib/libcairo.2.dylib"
copy_dylib "cairo/lib/libcairo-gobject.2.dylib"
copy_dylib "cairo/lib/libcairo-script-interpreter.2.dylib"
copy_dylib "harfbuzz/lib/libharfbuzz.0.dylib"
copy_dylib "harfbuzz/lib/libharfbuzz-subset.0.dylib"
copy_dylib "fribidi/lib/libfribidi.0.dylib"
copy_dylib "gdk-pixbuf/lib/libgdk_pixbuf-2.0.0.dylib"
copy_dylib "libepoxy/lib/libepoxy.0.dylib"
copy_dylib "graphene/lib/libgraphene-1.0.0.dylib"
copy_dylib "fontconfig/lib/libfontconfig.1.dylib"
copy_dylib "freetype/lib/libfreetype.6.dylib"
copy_dylib "gettext/lib/libintl.8.dylib"
copy_dylib "appstream/lib/libappstream.5.dylib"
copy_dylib "libpng/lib/libpng16.16.dylib"
copy_dylib "jpeg-turbo/lib/libjpeg.8.dylib"
copy_dylib "libtiff/lib/libtiff.6.dylib"
copy_dylib "webp/lib/libwebp.7.dylib"
copy_dylib "webp/lib/libwebpdemux.2.dylib"
copy_dylib "pcre2/lib/libpcre2-8.0.dylib"
copy_dylib "lzo/lib/liblzo2.2.dylib"
copy_dylib "pixman/lib/libpixman-1.0.dylib"
copy_dylib "brotli/lib/libbrotlidec.1.dylib"
copy_dylib "brotli/lib/libbrotlicommon.1.dylib"

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
    -i /usr/lib
    -i /System
)

# Fix .so extension modules
SO_FILES=()
for so in "$PY_SITEPACKAGES/gi/_gi.cpython"*".so" \
          "$PY_SITEPACKAGES/gi/_gi_cairo.cpython"*".so" \
          "$PY_SITEPACKAGES/cairo/_cairo.cpython"*".so"; do
    [ -f "$so" ] && SO_FILES+=(-x "$so")
done

dylibbundler -b -of \
    -x "$BUNDLED_PY/bin/python$PY_VER" \
    "${SO_FILES[@]}" \
    -d "$FRAMEWORKS/" \
    -p "@executable_path/../Frameworks/" \
    "${SEARCH_FLAGS[@]}" 2>/dev/null || true

# ── 8. gdk-pixbuf loaders ────────────────────────────────────────────────────
echo "==> Copying pixbuf loaders..."
PIXBUF_SRC="$BREW/lib/gdk-pixbuf-2.0/2.10.0/loaders"
PIXBUF_DEST="$RESOURCES/gdk-pixbuf/2.10.0/loaders"
mkdir -p "$PIXBUF_DEST"
find "$PIXBUF_SRC" \( -name "*.so" -o -name "*.dylib" \) \
    -exec cp {} "$PIXBUF_DEST/" \; 2>/dev/null || true

# Regenerate loaders.cache with bundle-relative paths
LOADERS_CACHE="$RESOURCES/gdk-pixbuf/loaders.cache"
"$BREW/bin/gdk-pixbuf-query-loaders" "$PIXBUF_DEST/"*.so > "$LOADERS_CACHE" 2>/dev/null || true
# Rewrite absolute paths to @RESOURCES@ placeholder (replaced at runtime by launcher)
sed -i '' "s|$(pwd)/$RESOURCES|@RESOURCES@|g" "$LOADERS_CACHE" 2>/dev/null || true

# ── 9. Create Python launch script ───────────────────────────────────────────
echo "==> Creating Python launcher..."
cat > "$RESOURCES/launch.py" << PYEOF
import os, sys, signal, gettext

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

# Fix loaders.cache paths at first run
LOADERS_CACHE="\$RESOURCES/gdk-pixbuf/loaders.cache"
if grep -q "@RESOURCES@" "\$LOADERS_CACHE" 2>/dev/null; then
    sed -i '' "s|@RESOURCES@|\$RESOURCES|g" "\$LOADERS_CACHE"
fi

export DYLD_FRAMEWORK_PATH="\$FRAMEWORKS"
export DYLD_LIBRARY_PATH="\$FRAMEWORKS:\${DYLD_LIBRARY_PATH:-}"
export PYTHONHOME="\$PY_FW"
export PYTHONPATH="\$PY_FW/lib/python$PY_VER/site-packages"
export GI_TYPELIB_PATH="\$RESOURCES/girepository-1.0"
export GSETTINGS_SCHEMA_DIR="\$RESOURCES/glib-2.0/schemas"
export XDG_DATA_DIRS="\$RESOURCES"
export GDK_PIXBUF_MODULE_FILE="\$RESOURCES/gdk-pixbuf/loaders.cache"

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

# ── 13. Bundle size summary ───────────────────────────────────────────────────
echo ""
echo "==> Bundle summary:"
du -sh "$FRAMEWORKS" "$RESOURCES" "$MACOS"
echo "Total:"
du -sh "$APP"

# ── 14. Create DMG ───────────────────────────────────────────────────────────
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
