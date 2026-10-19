"""Map where files physically sit on the archive HDD, as a static SVG.

Reads every file's physical extents with the FIEMAP ioctl (read-only, no root
needed) and draws the partition from its first block (top left) to its last
(bottom right): one panel coloured by content, one by when it was written.
The notes list free-space gap sizes, clip fragmentation and the copy speed of
the latest backup run, so maps from different days can be compared.

    python3 disk-map.py [mount] [-o out-dir]

Writes disk-map-YYYYMMDD-HHMM.svg (scan time) into out-dir, by default the
Jazz-Dashcam folder. Takes ~10 s; run it when no backup is copying, since
it makes the drive seek.
"""
import argparse, datetime as dt, fcntl, os, struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_MOUNT = "/media/surya/Surya_HDD_5"
DEFAULT_OUT = HERE.parent.parent              # Jazz-Dashcam/

# ---------- extents ----------
FS_IOC_FIEMAP = 0xC020660B
HDR = "=QQLLLL"          # start, length, flags, mapped_extents, extent_count, reserved
EXT = "=QQQQQLLLL"       # logical, physical, length, res64[2], flags, res32[3]
HSZ, ESZ = struct.calcsize(HDR), struct.calcsize(EXT)
BATCH = 512


def extents(fd):
    """[(physical_byte, length_bytes), ...] for an open file."""
    out, start = [], 0
    while True:
        buf = bytearray(struct.pack(HDR, start, 0xFFFFFFFFFFFFFFFF, 0, 0, BATCH, 0) + b"\0" * (ESZ * BATCH))
        fcntl.ioctl(fd, FS_IOC_FIEMAP, buf)
        n = struct.unpack_from(HDR, buf)[3]
        if n == 0:
            return out
        last = False
        for i in range(n):
            lo, ph, ln, _, _, fl, *_ = struct.unpack_from(EXT, buf, HSZ + i * ESZ)
            out.append((ph, ln))
            last |= bool(fl & 1)          # FIEMAP_EXTENT_LAST
            start = lo + ln
        if last:
            return out


def collect(root):
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != "lost+found"]
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.lstat(p)
                if not os.path.isfile(p) or os.path.islink(p):
                    continue
                fd = os.open(p, os.O_RDONLY)
                try:
                    ex = extents(fd)
                finally:
                    os.close(fd)
            except OSError:
                continue
            files.append({"p": os.path.relpath(p, root), "s": st.st_size, "c": st.st_ctime, "x": ex})
    return files


def partition_bytes(mount):
    """Size of the block device mounted at `mount` (statvfs hides ext4 overhead)."""
    for line in open("/proc/mounts"):
        dev, mnt = line.split()[:2]
        if mnt == mount and dev.startswith("/dev/"):
            name = os.path.basename(os.path.realpath(dev))
            return int(open(f"/sys/class/block/{name}/size").read()) * 512
    raise SystemExit(f"{mount} is not a mounted block device")


# ---------- categories ----------
CATS = ["normal", "event", "tl", "dashother", "otherbk", "meta", "free"]
LABEL = {"normal": "Raw Normal clips", "event": "Raw Event clips", "tl": "1 fps timelapses (pruned)",
         "dashother": "GPS, scripts, finished timelapses", "otherbk": "Other backups (repos, personal)",
         "meta": "ext4 metadata (inode tables)", "free": "Free"}
COLOR = {"normal": "#2a78d6", "event": "#eb6834", "tl": "#1baf7a", "dashother": "#eda100",
         "otherbk": "#e87ba4", "meta": "#898781", "free": "#e6e5df"}


def cat(p):
    b = p.rsplit("/", 1)[-1]
    if p.startswith("Jazz-Dashcam/70mai/"):
        if b.startswith("TL-"): return "tl"
        if b.startswith("NO"): return "normal"
        if b.startswith("EV"): return "event"
    return "dashother" if p.startswith("Jazz-Dashcam/") else "otherbk"


def is_clip(f):
    return f["p"].startswith("Jazz-Dashcam/70mai/") and f["p"].rsplit("/", 1)[-1][:2] in ("NO", "EV") and f["s"] > 1e6


def last_run(files):
    """Clips of the latest backup run: newest ctime cluster (gaps < 20 min)."""
    cl = sorted((f for f in files if is_clip(f)), key=lambda f: f["c"])
    run = cl[-1:]
    for a, b in zip(reversed(cl[:-1]), reversed(cl[1:])):
        if b["c"] - a["c"] > 1200:
            break
        run.insert(0, a)
    return run


def render(files, part_bytes, scanned, dest):
    B = 4096
    PART = part_bytes // B
    FLEX = 16 * 32768                         # ext4 flex_bg span (blocks)
    META_RUN = 8224                           # inode tables + bitmaps at each flex-group start
    COLS, ROWS = 500, 80
    CELL = -(-PART // (COLS * ROWS))           # blocks per cell
    NCELL = COLS * ROWS

    occ = np.zeros((len(CATS), NCELL))
    tw = np.zeros(NCELL)
    intervals = []

    def add(ci, start, length, t=None):
        end = start + length
        for c in range(start // CELL, min((end - 1) // CELL, NCELL - 1) + 1):
            lo, hi = max(start, c * CELL), min(end, (c + 1) * CELL)
            occ[ci, c] += hi - lo
            if t is not None:
                tw[c] += (hi - lo) * t

    for f in files:
        ci = CATS.index(cat(f["p"]))
        for ph, ln in f["x"]:
            add(ci, ph // B, ln // B or 1, f["c"])
            intervals.append((ph // B, (ph + ln) // B))
    # metadata positions are computed from the ext4 layout, not read
    for k in range(0, PART, FLEX):
        add(CATS.index("meta"), k, min(META_RUN, PART - k))
        intervals.append((k, min(k + META_RUN, PART)))
    cap = np.clip(np.minimum(CELL, PART - np.arange(NCELL) * CELL), 0, None)
    occ[CATS.index("free")] = np.clip(cap - occ.sum(0), 0, None)
    file_blocks = occ[:5].sum(0)
    tmean = np.where(file_blocks > 0, tw / np.maximum(file_blocks, 1), 0)
    dom = occ.argmax(0)

    # free gaps
    intervals.sort()
    gaps, cur = [], 0
    for s, e in intervals:
        if s > cur:
            gaps.append(s - cur)
        cur = max(cur, e)
    if cur < PART:
        gaps.append(PART - cur)
    gaps = np.array(gaps) * B / 1e9

    # write-age bins (sequential blue, light = old, dark = recent)
    now = scanned.timestamp()
    AGES = [(None, 56), (56, 28), (28, 14), (14, 7), (7, 2), (2, 0)]   # days ago (older, newer)
    SEQ = ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]

    def age_label(older, newer):
        d = lambda n: (scanned - dt.timedelta(days=n)).strftime("%-d %b")
        return f"before {d(newer)}" if older is None else f"{d(older)} – {d(newer)}" if newer else f"since {d(older)}"

    def tbin(t):
        days = (now - t) / 86400
        for i, (older, newer) in enumerate(AGES):
            if days >= newer and (older is None or days < older):
                return i
        return len(AGES) - 1

    # ---------- SVG ----------
    INK, INK2, MUTED, SURF = "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
    CW, RH, GAP = 2, 5, 1
    MAPH = ROWS * (RH + GAP) - GAP
    LM, W = 70, 70 + COLS * CW + 30
    out = []

    def text(x, y, s, size=12, fill=INK2, anchor="start", weight=400):
        out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>')

    row_gb = COLS * CELL * B / 1e9

    def draw_map(y0, colour_of):
        for r in range(ROWS):
            yy = y0 + r * (RH + GAP)
            run_c, run_s = None, 0
            for c in range(COLS + 1):
                col = colour_of(r * COLS + c) if c < COLS else None
                if col != run_c:
                    if run_c is not None:
                        out.append(f'<rect x="{LM + run_s * CW}" y="{yy}" width="{(c - run_s) * CW}" height="{RH}" fill="{run_c}"/>')
                    run_c, run_s = col, c
        for r in range(0, ROWS + 1, 10):
            yy = y0 + r * (RH + GAP) - (GAP if r else 0)
            text(LM - 8, yy + 4, f"{r * row_gb:,.0f} GB", 10, MUTED, "end")

    def legend(y0, items):
        x = LM
        for col, lab in items:
            out.append(f'<rect x="{x}" y="{y0 - 9}" width="10" height="10" rx="2" fill="{col}"/>')
            text(x + 15, y0, lab, 12, INK2)
            x += 15 + len(lab) * 6.6 + 20

    tot = {c: occ[i].sum() * B / 1e9 for i, c in enumerate(CATS)}
    y = 34
    text(LM, y, "Surya_HDD_5 — where the data physically sits", 20, INK, weight=600)
    y += 20
    text(LM, y, f"{part_bytes / 1e9:,.0f} GB partition, start of disk at top-left, read left to right, then down. "
         f"Each row = {row_gb:.1f} GB, each cell = {CELL * B / 1e6:.0f} MB, coloured by what fills most of it. "
         f"Scanned {scanned:%d %b %Y %H:%M}.", 11.5, INK2)

    y += 40
    text(LM, y, "1 · What is stored where", 15, INK, weight=600)
    y += 22
    legend(y, [(COLOR[c], f"{LABEL[c]} {tot[c]:,.0f} GB") for c in CATS[:4]])
    y += 18
    legend(y, [(COLOR[c], f"{LABEL[c]} {tot[c]:,.0f} GB") for c in CATS[4:]])
    y += 14
    draw_map(y, lambda i: COLOR[CATS[dom[i]]])
    y += MAPH + 40

    text(LM, y, "2 · When each part was written (file change time)", 15, INK, weight=600)
    y += 22
    legend(y, [(SEQ[i], age_label(*a)) for i, a in enumerate(AGES)] + [(COLOR["free"], "Free"), (COLOR["meta"], "Metadata")])
    y += 14
    draw_map(y, lambda i: SEQ[tbin(tmean[i])] if dom[i] < 5 else COLOR[CATS[dom[i]]])
    y += MAPH + 40

    # notes
    run = last_run(files)
    pcs = lambda fs: sum(len(f["x"]) for f in fs) / max(sum(f["s"] for f in fs) / 1e9, 1e-9)
    raw = [f for f in files if is_clip(f)]
    run_gb = sum(f["s"] for f in run) / 1e9
    chunks, acc, st, sb = [], 0, run[0]["c"], 0
    for f in run[1:]:
        acc += f["s"]
        if acc - sb >= 5e9:
            chunks.append(round((acc - sb) / 1e6 / max(f["c"] - st, 1)))
            st, sb = f["c"], acc
    notes = [
        f"Free space: {gaps.sum():,.0f} GB in {len(gaps):,} gaps — ≥1 GB: {gaps[gaps >= 1].sum():,.0f} GB, "
        f"0.1–1 GB: {gaps[(gaps >= 0.1) & (gaps < 1)].sum():,.0f} GB, under 0.1 GB: {gaps[gaps < 0.1].sum():,.0f} GB; "
        f"largest gap {gaps.max():,.1f} GB.",
        f"Latest backup run ({dt.datetime.fromtimestamp(run[0]['c']):%d %b %H:%M}): {len(run)} clips, {run_gb:,.1f} GB, "
        f"{pcs(run):.0f} pieces per GB (all raw clips: {pcs(raw):.0f}). MB/s per 5 GB: {', '.join(map(str, chunks)) or 'n/a'}.",
        "Over ~50 pieces per GB (pieces under ~20 MB) went with SMR slowdowns in earlier runs; 85 MB/s is about the card reader's ceiling.",
        "Grey dots every 2 GB are ext4 inode tables (~25 GB in all). FIEMAP sees files only, so their positions are computed, not read.",
    ]
    text(LM, y, "3 · Notes", 15, INK, weight=600)
    y += 20
    for n in notes:
        text(LM, y, "• " + n, 11.5, INK2)
        y += 18
    H = y + 16
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="system-ui, -apple-system, Segoe UI, Ubuntu, sans-serif">'
           f'<rect width="100%" height="100%" fill="{SURF}"/>' + "".join(out) + "</svg>")
    Path(dest).write_text(svg)
    return notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mount", nargs="?", default=DEFAULT_MOUNT)
    ap.add_argument("-o", "--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    scanned = dt.datetime.now()
    files = collect(a.mount)
    dest = Path(a.out_dir) / f"disk-map-{scanned:%Y%m%d-%H%M}.svg"
    for n in render(files, partition_bytes(a.mount), scanned, dest):
        print("•", n)
    print(dest)


if __name__ == "__main__":
    main()
