#!/usr/bin/env python3
"""The newest ChituLinux release on GitHub.

latest            print the version, then the URLs of the AppImage and of SHA256SUMS, one per line
download URL FILE download to FILE, printing the percentage done per line (for zenity --progress)
chitubox CURRENT FILE  the CHITUBOX version of installer FILE (as CHITUBOX's update downloads it, by its hash):
                  asks CHITUBOX's update server what follows CURRENT and compares the MD5

The version comes from where releases/latest redirects to, not from GitHub's API and its rate limit.
"""
import hashlib
import json
import os
import sys
import urllib.request

REPO = 'MichielBruijn/chitulinux'


def get(url, method='GET'):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 'chitulinux'}, method=method), timeout=20)


def latest():
    with get(f'https://github.com/{REPO}/releases/latest', 'HEAD') as r:
        tag = r.geturl().rstrip('/').rsplit('/', 1)[-1]
    if not tag.startswith('v'):
        sys.exit(f'no release found ({r.geturl()})')
    base = f'https://github.com/{REPO}/releases/download/{tag}/'
    print(tag[1:], f'{base}ChituLinux-{tag[1:]}-x86_64.AppImage', f'{base}SHA256SUMS', sep='\n')


def download(url, path):
    with get(url) as r, open(path + '.part', 'wb') as f:
        size, done, shown = int(r.headers.get('Content-Length') or 0), 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if size and done * 100 // size != shown:
                shown = done * 100 // size
                print(min(shown, 99), flush=True)  # 100 closes the progress dialog
    os.replace(path + '.part', path)
    print(100, flush=True)


def chitubox(current, path):
    url = ('https://sac.chitubox.com/PCVersionUpdate/getInfo.do6?softwareType=17952&platform=1'
           f'&majorVersion=v{current}&silentVersion=0.0.0&login=0&customerMail=0')
    with get(url) as r:
        found = (json.load(r).get('data') or {}).get('versionUpdateResult') or []
    md5 = hashlib.md5()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20):
            md5.update(chunk)
    for u in found:
        if str(u.get('packageHash', '')).lower() == md5.hexdigest():
            print(u['version'])
            return
    sys.exit('not a CHITUBOX update')


if __name__ == '__main__':
    if sys.argv[1:2] == ['latest']:
        latest()
    elif sys.argv[1:2] == ['download'] and len(sys.argv) == 4:
        download(sys.argv[2], sys.argv[3])
    elif sys.argv[1:2] == ['chitubox'] and len(sys.argv) == 4:
        chitubox(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
