#!/bin/bash
# Build ChituLinux-<version>-x86_64.AppImage.
#
# usage: ./build.sh [WINE_DIST]
#   WINE_DIST  folder with a built Wine (usr/bin, usr/lib/wine, ...), as made by wine/build-wine.sh;
#              built from source when left out
set -eu
TOP="$(dirname "$(readlink -f "$0")")"
BUILD="$TOP/build"
DIR="$BUILD/AppDir"
VERSION="$(cat "$TOP/VERSION")"
OUT="$TOP/ChituLinux-$VERSION-x86_64.AppImage"
TOOLS="$DIR/usr/lib/chitulinux"
DXVK_VERSION=2.7.1
DXVK_SHA256=d85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87
mkdir -p "$BUILD"

# --- Wine -------------------------------------------------------------------------------------------
WINE_DIST="${1:-$BUILD/wine-dist}"
[ -x "$WINE_DIST/usr/bin/wine" ] || "$TOP/wine/build-wine.sh" "$WINE_DIST"

rm -rf "$DIR"
mkdir -p "$DIR/usr" "$TOOLS" "$DIR/usr/share/chitulinux" "$DIR/usr/share/doc/chitulinux"
cp -a "$WINE_DIST/usr/bin" "$WINE_DIST/usr/lib" "$WINE_DIST/usr/share" "$DIR/usr/"
"$TOP/wine/strip-wine.sh" "$DIR"

# --- DXVK -------------------------------------------------------------------------------------------
tarball="$BUILD/dxvk-$DXVK_VERSION.tar.gz"
[ -f "$tarball" ] ||
    curl -fL -o "$tarball" "https://github.com/doitsujin/dxvk/releases/download/v$DXVK_VERSION/dxvk-$DXVK_VERSION.tar.gz"
echo "$DXVK_SHA256  $tarball" | sha256sum -c --quiet
mkdir -p "$TOOLS/dxvk"
tar -xzf "$tarball" -C "$TOOLS/dxvk" --strip-components=1 \
    "dxvk-$DXVK_VERSION/x64" "dxvk-$DXVK_VERSION/x32"

# --- appimagetool and the AppImage runtime ----------------------------------------------------------
[ -f "$BUILD/appimagetool.AppImage" ] ||
    curl -fL -o "$BUILD/appimagetool.AppImage" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
[ -f "$BUILD/runtime-x86_64" ] ||
    curl -fL -o "$BUILD/runtime-x86_64" https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64
chmod +x "$BUILD/appimagetool.AppImage"

# --- ChituLinux itself ------------------------------------------------------------------------------
cp "$TOP/tools/settings.py" "$TOP/tools/exeicon.py" "$TOP/tools/chitulinux-release.py" "$TOP/tools/rpp-bridge.py" "$TOP/tools/wait-window.py" "$TOP/tools/desktop-dpi" "$TOOLS/"
cp "$TOP/VERSION" "$DIR/usr/share/chitulinux/VERSION"
cp "$TOP/README.md" "$TOP/LICENSE" "$TOP/NOTICE.md" "$DIR/usr/share/doc/chitulinux/"
cp "$TOP/chitulinux-run" "$DIR/AppRun"
chmod +x "$DIR/AppRun"
cp "$TOP/chitulinux.png" "$DIR/"
ln -s chitulinux.png "$DIR/.DirIcon"
cat > "$DIR/chitulinux.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=CHITUBOX
Comment=CHITUBOX on Linux
Exec=AppRun %F
Icon=chitulinux
Categories=Graphics;3DGraphics;
Terminal=false
EOF

{
    echo "ChituLinux $VERSION"
    echo "Wine: upstream $(cat "$TOP/wine/UPSTREAM_COMMIT") with the patches in wine/patches"
    echo "DXVK: $DXVK_VERSION"
} > "$DIR/usr/share/doc/chitulinux/bundled-versions.txt"

# everything bundled must run from glibc 2.38 on (Ubuntu 24.04, Debian 13, Fedora 39), whatever this machine has
need="$(find "$DIR/usr/bin" "$DIR/usr/lib/wine/"*-unix -type f -exec objdump -T {} + 2>/dev/null |
    grep -o 'GLIBC_2\.[0-9]*' | sort -uV | tail -1)"
[ "$(printf '%s\n' "$need" GLIBC_2.38 | sort -V | tail -1)" = GLIBC_2.38 ] ||
    { echo "error: the bundled programs need $need, more than GLIBC_2.38" >&2; exit 1; }

ARCH=x86_64 "$BUILD/appimagetool.AppImage" --comp zstd --runtime-file "$BUILD/runtime-x86_64" "$DIR" "$OUT"
ls -la "$OUT"
# for the release, and for the AppImage's own update check
(cd "$TOP" && sha256sum "$(basename "$OUT")" > SHA256SUMS)
