# Notices

## Trademarks

CHITUBOX is a trademark of CBD-Tech (Shenzhen CBD Technology Co., Ltd.). Windows and Direct3D are
trademarks of Microsoft. ChituLinux is an independent, unofficial project. It is not affiliated with,
endorsed by or supported by CBD-Tech or Microsoft.

## What ChituLinux does and does not contain

The AppImage contains **no** CHITUBOX files. CHITUBOX is installed from the Windows installer the user
downloads from chitubox.com, under the license agreement of that installer. The icon of the app menu entry
is taken from the installed `CHITUBOX.exe` on the user's computer.

## Bundled third-party software

| Component | License | Source |
|-----------|---------|--------|
| Wine, with the patches in `wine/patches` | LGPL 2.1 or later | https://gitlab.winehq.org/wine/wine at the commit in `wine/UPSTREAM_COMMIT`, plus `wine/patches` (build with `wine/build-wine.sh`) |
| DXVK | zlib | https://github.com/doitsujin/dxvk, version in `build.sh` |
| AppImage type 2 runtime | MIT | https://github.com/AppImage/type2-runtime |

`tools/desktop-dpi` and `tools/exeicon.py` and the Wine patches 0001–0087 come from
[TopSo'Linux](https://github.com/MichielBruijn/topsolinux) (MIT, Wine patches LGPL 2.1 or later).

On request, the exact source code of the bundled Wine in a released AppImage is provided for three years
after that release (open an issue on the project page).
