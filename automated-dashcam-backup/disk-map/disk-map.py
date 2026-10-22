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
import argparse, datetime as dt, fcntl, os, re, struct
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


DASH_NAME = re.compile(r"^(?:TL-)?(?:NO|EV|PA)(\d{8})-(\d{6})")


def recorded(name, fallback):
    """Recording time from a dashcam name (NO/EV, with or without the TL- prefix of a
    1 fps timelapse); other files fall back to when they were written (ctime)."""
    m = DASH_NAME.match(name)
    if m:
        try:
            return dt.datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            pass
    return fallback


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
            files.append({"p": os.path.relpath(p, root), "s": st.st_size, "c": st.st_ctime,
                          "r": recorded(fn, st.st_ctime), "x": ex})
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
# Dark page: categorical hues are the dark-mode steps of the default palette;
# free space is a dim grey just above the page, so it reads as empty.
COLOR = {"normal": "#3987e5", "event": "#d95926", "tl": "#199e70", "dashother": "#c98500",
         "otherbk": "#d55181", "meta": "#6f6e69", "free": "#2f2f2c"}


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
    COLS, ROWS = 288, 152                     # two panels side by side on a 1920x1080 page
    CELL = -(-PART // (COLS * ROWS))           # blocks per cell
    NCELL = COLS * ROWS

    occ = np.zeros((len(CATS), NCELL))
    KINDS = ["tl", "raw", "other"]             # date panel: each kind coloured on its own
    KIND_OF = {"tl": 0, "normal": 1, "event": 1, "dashother": 2, "otherbk": 2}
    tw = np.zeros((3, NCELL))                  # recording time x blocks, per kind
    bw = np.zeros((3, NCELL))                  # blocks, per kind
    intervals = []

    def add(ci, start, length, t=None, k=None):
        end = start + length
        for c in range(start // CELL, min((end - 1) // CELL, NCELL - 1) + 1):
            lo, hi = max(start, c * CELL), min(end, (c + 1) * CELL)
            occ[ci, c] += hi - lo
            if t is not None:
                tw[k, c] += (hi - lo) * t
                bw[k, c] += hi - lo

    for f in files:
        cn = cat(f["p"])
        ci = CATS.index(cn)
        for ph, ln in f["x"]:
            add(ci, ph // B, ln // B or 1, f["r"], KIND_OF[cn])
            intervals.append((ph // B, (ph + ln) // B))
    # metadata positions are computed from the ext4 layout, not read
    for k in range(0, PART, FLEX):
        add(CATS.index("meta"), k, min(META_RUN, PART - k))
        intervals.append((k, min(k + META_RUN, PART)))
    cap = np.clip(np.minimum(CELL, PART - np.arange(NCELL) * CELL), 0, None)
    occ[CATS.index("free")] = np.clip(cap - occ.sum(0), 0, None)
    kind = bw.argmax(0)                        # the kind filling most of each cell
    tmean = tw[kind, np.arange(NCELL)] / np.maximum(bw[kind, np.arange(NCELL)], 1)
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

    # recording-date colour: one continuous viridis band (perceptually even and
    # made for dark backgrounds: dark = old, bright = new) split 50/50. 1 fps
    # timelapses take the dark half (purple -> blue), raw clips the bright half
    # (teal -> green -> yellow), and each kind is stretched over its own date
    # range, so the short span of recent raw clips gets as much colour as the long
    # timelapse span. Each range starts where that kind's oldest 1% of data ends
    # (older files take the first colour of the half). Other files (GPS, scripts,
    # other backups) are one neutral; their dates don't matter here.
    # Legend swatches are references: the mean colour of each date slice.
    HALVES = [["#472d7b", "#3e4a89", "#31688e", "#26828e"],      # timelapses
              ["#1f9e89", "#35b779", "#90d743", "#fde725"]]      # raw clips
    OTHER_COL = "#8c8778"
    hexrgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    fmt = lambda t: dt.datetime.fromtimestamp(t).strftime("%-d %b")

    def span(k):
        fc = sorted((f["r"], f["s"]) for f in files if KIND_OF.get(cat(f["p"])) == k)
        if not fc:
            return None
        acc, total, lo = 0, sum(z for _, z in fc), fc[0][0]
        for t, z in fc:
            acc += z
            if acc >= 0.01 * total:
                lo = t
                break
        return lo, fc[-1][0], fc[0][0]

    SPANS = [span(0), span(1)]

    def kind_colour(k, t):
        if k == 2 or SPANS[k] is None:
            return OTHER_COL
        lo, hi, _ = SPANS[k]
        ramp = np.array([hexrgb(h) for h in HALVES[k]], float)
        u = min(max((t - lo) / max(hi - lo, 1), 0.0), 1.0) * (len(ramp) - 1)
        i = min(int(u), len(ramp) - 2)
        c = ramp[i] + (ramp[i + 1] - ramp[i]) * (u - i)
        return "#%02x%02x%02x" % tuple(int(round(v)) for v in c)

    def legend_row(k, name, n=4):
        if SPANS[k] is None:
            return []
        lo, hi, first = SPANS[k]
        e = [lo + (hi - lo) * j / n for j in range(n + 1)]
        row = [(kind_colour(k, (e[j] + e[j + 1]) / 2), f"{fmt(e[j])}–{fmt(e[j + 1])}") for j in range(n)]
        if first < lo:
            row[0] = (row[0][0], f"to {fmt(e[1])}")
        return [(None, name)] + row

    # ---------- SVG ----------
    INK, INK2, MUTED, SURF = "#f0efec", "#c3c2b7", "#8f8e86", "#1a1a19"
    CW, RH, GAP = 3, 4, 1
    MAPH = ROWS * (RH + GAP) - GAP
    W, H = 1920, 1080                          # 16:9
    LM = 70                                    # left edge of panel 1 (GB labels sit left of it)
    PX = [LM, LM + COLS * CW + 90]             # x of each panel
    out = []

    def text(x, y, s, size=12, fill=INK2, anchor="start", weight=400):
        out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>')

    row_gb = COLS * CELL * B / 1e9

    def draw_map(x0, y0, colour_of):
        for r in range(ROWS):
            yy = y0 + r * (RH + GAP)
            run_c, run_s = None, 0
            for c in range(COLS + 1):
                col = colour_of(r * COLS + c) if c < COLS else None
                if col != run_c:
                    if run_c is not None:
                        out.append(f'<rect x="{x0 + run_s * CW}" y="{yy}" width="{(c - run_s) * CW}" height="{RH}" fill="{run_c}"/>')
                    run_c, run_s = col, c
        for r in range(0, ROWS + 1, 10):
            yy = y0 + r * (RH + GAP) - (GAP if r else 0)
            text(x0 - 8, yy + 4, f"{r * row_gb:,.0f} GB", 10, MUTED, "end")

    def legend(x0, y0, items):
        x = x0
        for col, lab in items:
            if col is None:                    # row heading, no swatch
                text(x, y0, lab, 12, INK, weight=600)
                x += len(lab) * 6.8 + 12
                continue
            out.append(f'<rect x="{x}" y="{y0 - 9}" width="10" height="10" rx="2" fill="{col}"/>')
            text(x + 15, y0, lab, 12, INK2)
            x += 15 + len(lab) * 6.6 + 20

    tot = {c: occ[i].sum() * B / 1e9 for i, c in enumerate(CATS)}
    text(LM, 40, "Surya_HDD_5 — where the data physically sits", 22, INK, weight=600)
    text(LM, 64, f"{part_bytes / 1e9:,.0f} GB partition, start of disk at top-left of each panel, read left to right, then down. "
         f"Each row = {row_gb:.1f} GB, each cell = {CELL * B / 1e6:.0f} MB, coloured by what fills most of it. "
         f"Scanned {scanned:%d %b %Y %H:%M}.", 12, INK2)

    top = 104
    lg = lambda k: (COLOR[k], f"{LABEL[k]} {tot[k]:,.0f} GB")
    x = PX[0]
    text(x, top, "1 · What is stored where", 16, INK, weight=600)
    legend(x, top + 24, [lg("normal"), lg("event"), lg("tl")])
    legend(x, top + 42, [lg("dashother"), lg("otherbk")])
    legend(x, top + 60, [lg("meta"), lg("free")])
    x = PX[1]
    text(x, top, "2 · When it was recorded (from filenames) — dark = oldest, bright = newest", 16, INK, weight=600)
    legend(x, top + 24, legend_row(0, "1 fps timelapses:"))
    legend(x, top + 42, legend_row(1, "Raw clips:"))
    legend(x, top + 60, [(OTHER_COL, "Other files (GPS, scripts, other backups)"), (COLOR["free"], "Free"), (COLOR["meta"], "Metadata")])

    map_top = top + 78
    draw_map(PX[0], map_top, lambda i: COLOR[CATS[dom[i]]])
    draw_map(PX[1], map_top, lambda i: kind_colour(kind[i], tmean[i]) if dom[i] < 5 else COLOR[CATS[dom[i]]])
    y = map_top + MAPH + 34

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
    text(LM, y, "3 · Notes", 16, INK, weight=600)
    y += 22
    for n in notes:
        text(LM, y, "• " + n, 12, INK2)
        y += 19
    if y - 19 > H - 8:
        print(f"warning: notes run past the 1080 px page ({y - 19:.0f})")
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
