"""Check every pack file against the bytes git will actually serve.

Run this from the publishing worktree (gh-pages) with the site staged, BEFORE
pushing:

    python mobileapp/tools/verify_published_packs.py

It hashes the STAGED blob for each manifest entry - the exact bytes that get
pushed, and therefore exactly what GitHub Pages serves - and compares it to
the SHA-256 the manifest publishes. Anything git transformed on the way in
shows up here rather than on a farmer's phone.

It has caught this once already: build_pack.py wrote JSON in text mode, so on
Windows the files were CRLF on disk, git normalised them back to LF, and three
of the ten potato files no longer matched the hashes published alongside them.
The installer would have refused the pack - correctly, and unhelpfully, since
the pack was ours.
"""
import json, hashlib, subprocess, glob, posixpath

SEP = chr(92)  # backslash, built without escaping so no shell mangles it
total = bad = 0
for raw in sorted(glob.glob('packs/*/*/manifest.json')):
    mpath = raw.replace(SEP, '/')
    base = posixpath.dirname(mpath)
    m = json.load(open(mpath, encoding='utf-8'))
    for f in m['files']:
        path = posixpath.join(base, f['path'])
        r = subprocess.run(['git', 'show', ':' + path], capture_output=True)
        total += 1
        if not r.stdout or hashlib.sha256(r.stdout).hexdigest() != f['sha256']:
            bad += 1
            print('MISMATCH', path, '(%d bytes)' % len(r.stdout))
print('%d files checked against what git will serve, %d mismatches' % (total, bad))
raise SystemExit(1 if bad else 0)
