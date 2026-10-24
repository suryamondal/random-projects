#!/usr/bin/env python3
"""Backup 70mai dashcam videos + GPS data from the SD card to the HDD.

- Prune: before copying, replaces the oldest recordings in the backup with
  1 fps timelapses so that existing + incoming files stay under
  PRUNE_LIMIT_BYTES. Event/ clips are pruned over the same time range as
  Normal/, so no full-resolution event survives from a period whose normal
  footage is already a timelapse. Pruned files are listed in pruned.txt
  and never re-copied from the card.
- Videos: rsync -au of Normal/Event/Parking/Lapse/Photo, skipping files
  that already exist in the backup.
- GPS: snapshots the card's GPSData*.txt files verbatim into GPS/, named
  by the timestamp of the first valid fix in the file. The same card's
  growing file replaces its own snapshot; different cards (different
  first fix) get separate snapshots, so backup order never matters.
  Identical content is skipped; diverging content on the same name is
  kept side by side instead of overwritten. (GPSData.txt in the backup
  root is the legacy merged master, no longer updated.)

Two processes share this file, so the card is never kept waiting:

- Stager (--stage, "A"): reads the card once, at full speed, into a batch
  folder on the NVMe (STAGING_ROOT), checks every clip, and marks the batch
  complete. The card can be removed as soon as it logs "card can be removed".
  It refuses to start if the NVMe has less than 1.5x the new data free, and
  only one stager runs at a time.
- Backup (default, "B"): runs from cron every 5 minutes, card or no card.
  Each run first launches the stager (a no-op if one is already running),
  then moves complete batches to the HDD: prune, copy, verify, GPS, disk map.
  While the stager is still reading a card, it prunes for that card ahead of
  time. If the stager can't stage (no NVMe space, staging failed), it copies
  straight from the card as before.

Pruning is safe to repeat: every run measures the HDD afresh and frees only
what is still missing, so a crash or power cut can never make it prune twice.

Usage: python3 backup-dashcam.py [source_mount] [dest_dir]
       python3 backup-dashcam.py --stage [source_mount] [dest_dir]
       python3 backup-dashcam.py --verify-all   # probe every clip already backed up
"""

import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_SRC = "/media/surya/70MAI"
DEFAULT_DEST = "/media/surya/Surya_HDD_5/Jazz-Dashcam/70mai"
VIDEO_DIRS = ["Normal", "Event", "Parking", "Lapse", "Photo"]
# Storage cap for the whole backup directory, GPS/ and existing timelapses
# included (those are never pruned, but they count). Before copying, the
# oldest recordings are pruned until the incoming files fit.
PRUNE_LIMIT_BYTES = int(os.environ.get("DASHCAM_PRUNE_LIMIT",
                                       1_250_000_000_000))  # 1.25 TB
# Directories whose recordings are never pruned. Event/ used to be here; it is
# now pruned over the same time range as Normal/ (see prune_events_in_range).
PRUNE_PROTECTED: set[str] = set()
# Files deleted by pruning are recorded here (one filename per line) and
# excluded from future rsyncs, so a pruned file still present on the card
# is never copied back in.
PRUNED_LIST = "pruned.txt"
# Clips that would not open even after being fetched from the card again are
# logged here (timestamp + path, one per line) rather than silently kept.
CORRUPT_LIST = "corrupt.txt"
# After this many failed re-copies a clip is left alone. Without a cap, a clip
# that is bad on the card itself would be re-pulled (~200 MB) on every run.
MAX_RECOPY_ATTEMPTS = 3
# The 70mai camera writes this signature file to every card it records on.
# Requiring it means an automated/cron run only ever backs up a card that
# was actually used in the dashcam — never some other removable device
# that happens to be mounted at the source path.
CAMERA_MARKER = ".used.file.DR2500"

# Staging area for the stager. Each card read becomes one batch folder
# (YYYYMMDD-HHMMSS-<card volume id>) holding the new clips, the card's GPS
# files and .batch.json (state, file list with sizes).
STAGING_ROOT = Path(os.environ.get("DASHCAM_STAGING",
                                   "/media/surya/Surya_NVME_1/dashcam-staging"))
STAGE_SPACE_FACTOR = float(os.environ.get("DASHCAM_STAGE_FACTOR", 1.5))  # NVMe must have 1.5x the new data free
STAGE_LOCK = ".stage.lock"        # held by the running stager
STAGE_STATUS = ".stage-status.json"
BATCH_STATE = ".batch.json"
# The backup stops waiting for a stager whose batch has not grown for this long.
STAGE_STALL_SECONDS = 15 * 60
# A half-staged batch whose card never came back is moved to the HDD anyway
# (readable clips only) once it has been left alone this long.
ABANDONED_SECONDS = int(os.environ.get("DASHCAM_ABANDONED_SECONDS", 30 * 60))
LOG_FILE = Path(os.environ.get("DASHCAM_LOG",
                               Path(__file__).resolve().parent / "backup.log"))
# Tests point the source at a plain folder; this skips the mount-point check.
TEST_MODE = os.environ.get("DASHCAM_TEST") == "1"


def card_present(src: Path) -> bool:
    return (TEST_MODE and src.is_dir() or os.path.ismount(src)) \
        and (src / CAMERA_MARKER).exists()


def verify_source_device(src: Path) -> None:
    if not TEST_MODE and not os.path.ismount(src):
        sys.exit(f"ERROR: '{src}' is not a mount point — no card inserted?")
    if not (src / CAMERA_MARKER).exists():
        sys.exit(
            f"ERROR: '{src}' has no '{CAMERA_MARKER}' signature — not a "
            f"70mai dashcam card, refusing to back up an unknown device."
        )
    if not (src / "Normal").is_dir() and not list(src.glob("GPSData*.txt")):
        sys.exit(f"ERROR: '{src}' has no Normal/ or GPSData*.txt — nothing to back up.")


def recording_key(f: Path) -> str:
    """Chronological sort key: the YYYYMMDDHHMMSS timestamp embedded in
    70mai filenames (NO20260728-131217-...), falling back to mtime."""
    m = re.search(r"(\d{8})-(\d{6})", f.name)
    if m:
        return m.group(1) + m.group(2)
    return datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y%m%d%H%M%S")



# Before a recording is pruned it is replaced, in place, by a 1-frame-per-second
# timelapse built from the clip's keyframes (the camera writes one per second).
# Original timestamps and the audio track are kept, so the timelapse still runs
# for the same 60 seconds and second N still shows second N.
TIMELAPSE_PREFIX = "TL-"
TIMELAPSE_CRF = "30"


def is_timelapse(f: Path) -> bool:
    return f.name.startswith(TIMELAPSE_PREFIX)


def make_timelapse(f: Path) -> Path | None:
    """Write TL-<name> beside f. Returns the new file, or None on failure."""
    if f.suffix.upper() != ".MP4":
        return None
    out = f.with_name(TIMELAPSE_PREFIX + f.name)
    if out.exists():
        return out
    tmp = f.with_name(TIMELAPSE_PREFIX + f.stem + ".part" + f.suffix)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-skip_frame", "nokey",
           "-i", str(f), "-fps_mode", "passthrough", "-c:v", "libx264",
           "-crf", TIMELAPSE_CRF, "-preset", "veryfast", "-c:a", "copy",
           "-movflags", "+faststart", str(tmp)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=600)
        if tmp.stat().st_size < 10_000:
            raise RuntimeError("timelapse suspiciously small")
    except Exception:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out


def prunable_backup_files(dest: Path) -> list[Path]:
    files = []
    for dirname in VIDEO_DIRS:
        if dirname in PRUNE_PROTECTED:
            continue
        d = dest / dirname
        if d.is_dir():
            files.extend(f for f in d.rglob("*") if f.is_file())
    return files


def total_backup_bytes(dest: Path) -> int:
    """Every byte under the backup root.

    The limit is measured against the whole 70mai directory -- GPS/ and the
    timelapses included -- even though those are never deleted to satisfy it.
    """
    if not dest.is_dir():
        return 0
    return sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())


def incoming_bytes(src: Path, dest: Path, pruned: set[str]) -> int:
    """Size of card files the next copy would add, protected dirs included,
    because they count against the limit even though they cannot be pruned."""
    total = 0
    for dirname in VIDEO_DIRS:
        src_dir = src / dirname
        if not src_dir.is_dir():
            continue
        for f in src_dir.rglob("*"):
            if not f.is_file() or f.name.startswith(".") or f.name in pruned:
                continue
            dest_file = dest / f.relative_to(src)
            if not dest_file.exists():
                total += f.stat().st_size
    return total


def load_pruned(dest: Path) -> set[str]:
    pruned_file = dest / PRUNED_LIST
    return set(pruned_file.read_text().split()) if pruned_file.exists() else set()


def record_pruned(plog, name: str) -> None:
    """Write the name to pruned.txt and force it to disk BEFORE the file is
    deleted. A power cut in between then leaves a listed file that still
    exists (the next prune finishes the job) instead of a deleted file that
    is not listed (which could be copied back in from the card)."""
    plog.write(name + "\n")
    plog.flush()
    os.fsync(plog.fileno())


def prune_old_files(dest: Path, needed: int, limit: int = PRUNE_LIMIT_BYTES) -> None:
    """Replace the oldest recordings with timelapses until `needed` more bytes
    fit under the storage limit.

    Nothing is carried over between runs: usage is measured afresh every time,
    so a run that died half way is simply finished by the next one.
    """
    pruned_file = dest / PRUNED_LIST
    existing = prunable_backup_files(dest)
    used = total_backup_bytes(dest)
    deletable = sum(f.stat().st_size for f in existing if not is_timelapse(f))
    print(f"  backup uses {used / 1e9:.1f} GB, incoming {needed / 1e9:.1f} GB, "
          f"limit {limit / 1e9:.1f} GB")
    print(f"  deletable: {deletable / 1e9:.1f} GB "
          f"(GPS/ and existing timelapses count but cannot be freed)")
    excess = used + needed - limit
    if excess <= 0:
        print("  nothing to prune")
        prune_events_in_range(dest, pruned_file)
        return
    if excess > deletable:
        print(f"  !! need {excess / 1e9:.1f} GB but only {deletable / 1e9:.1f} GB "
              f"is deletable -- the limit will be exceeded")

    existing.sort(key=recording_key)
    freed = 0
    removed = 0
    with pruned_file.open("a") as plog:
        lapsed = 0
        kept = 0
        for f in existing:
            if freed >= excess:
                break
            if is_timelapse(f):          # never prune the timelapses themselves
                continue
            size = f.stat().st_size
            tl = make_timelapse(f)
            if tl is None and f.suffix.upper() == ".MP4":
                kept += 1                # encode failed - keep the original
                continue
            record_pruned(plog, f.name)
            f.unlink()
            freed += size - (tl.stat().st_size if tl else 0)
            removed += 1
            if tl is not None:
                lapsed += 1
    print(f"  pruned {removed} oldest files, freed {freed / 1e9:.1f} GB "
          f"({lapsed} replaced by 1 fps timelapses)")
    if kept:
        print(f"  !! {kept} files kept because the timelapse could not be made")
    prune_events_in_range(dest, pruned_file)


def prune_events_in_range(dest: Path, pruned_file: Path) -> None:
    """Timelapse every Event/ clip no newer than the newest pruned Normal/ clip.

    The main prune walks Normal/ and Event/ together in time order and stops
    as soon as enough is freed, so it can stop inside a stretch that still
    has full-resolution events. This sweep makes the two ranges match, and it
    also catches up the events kept from before Event/ was prunable. It runs
    on every backup and does nothing once the ranges already agree.
    """
    normal = dest / "Normal"
    lapsed_normal = [f for f in normal.rglob(TIMELAPSE_PREFIX + "*")
                     if f.is_file() and ".part." not in f.name] \
        if normal.is_dir() else []
    event = dest / "Event"
    if not lapsed_normal or not event.is_dir():
        return
    cutoff = max(recording_key(f) for f in lapsed_normal)
    todo = sorted((f for f in event.rglob("*") if f.is_file()
                   and not is_timelapse(f) and ".part." not in f.name
                   and recording_key(f) <= cutoff), key=recording_key)
    if not todo:
        return
    freed = lapsed = kept = 0
    with pruned_file.open("a") as plog:
        for f in todo:
            size = f.stat().st_size
            tl = make_timelapse(f)
            if tl is None and f.suffix.upper() == ".MP4":
                kept += 1
                continue
            record_pruned(plog, f.name)
            f.unlink()
            freed += size - (tl.stat().st_size if tl else 0)
            lapsed += tl is not None
    print(f"  events up to {cutoff[:8]}-{cutoff[8:]}: {lapsed} replaced by 1 fps "
          f"timelapses, freed {freed / 1e9:.1f} GB")
    if kept:
        print(f"  !! {kept} event files kept because the timelapse could not be made")


def clip_readable(path: Path) -> bool:
    """True if ffmpeg can actually open this file.

    rsync only compares size and mtime, so a bad read off the card is copied
    faithfully and then never re-copied, because the sizes still match. The
    file is the right length and plays in tolerant players; ffmpeg refuses it.
    One such file reached the archive this way
    (NO20260926-123211-000043F.MP4: 9 of 1800 entries in the third track's
    sample-size table were garbage). Only a decoder-level probe catches it.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True)
    return probe.returncode == 0 and probe.stdout.strip() not in (b"", b"N/A")


def recopy(src_file: Path, dest_file: Path) -> bool:
    """Fetch a bad copy again from the card. True if the new copy verifies.

    The old copy is only removed once the fresh one is in place, so a failure
    here never turns a bad file into a missing one.
    """
    if not src_file.exists():
        return False
    fresh = dest_file.with_suffix(dest_file.suffix + ".refetch")
    try:
        result = subprocess.run(
            ["rsync", "-a", "--modify-window=2", str(src_file), str(fresh)])
        if result.returncode != 0 or not clip_readable(fresh):
            fresh.unlink(missing_ok=True)
            return False
        fresh.replace(dest_file)
        return True
    except OSError:
        fresh.unlink(missing_ok=True)
        return False


def quarantine_count(quarantine: Path, rel: str) -> int:
    """How many times this clip has already failed a re-copy."""
    if not quarantine.exists():
        return 0
    return sum(1 for line in quarantine.read_text(errors="replace").splitlines()
               if line.partition("\t")[2].strip() == rel)


def verify_copied(src_dir: Path, dest_dir: Path, names: list[str],
                  quarantine: Path) -> list[str]:
    """Probe every clip just copied; re-fetch any that will not open.

    This runs while the card is still mounted, which is the only moment a bad
    copy can be repaired from its source.
    """
    unresolved = []
    checked = repaired = 0
    for rel in names:
        dest_file = dest_dir / rel
        if dest_file.suffix.upper() != ".MP4" or not dest_file.exists():
            continue
        checked += 1
        if clip_readable(dest_file):
            continue
        tried = quarantine_count(quarantine, rel)
        if tried >= MAX_RECOPY_ATTEMPTS:
            # Give up rather than re-pull 200 MB on every 5-minute cron run.
            unresolved.append(rel)
            print(f"  !! {rel} unreadable, {tried} re-copies already failed "
                  f"— leaving it alone")
            continue
        print(f"  !! {rel} did not verify — re-copying from the card")
        if recopy(src_dir / rel, dest_file):
            repaired += 1
            print(f"     re-copied and verified: {rel}")
        else:
            unresolved.append(rel)
            print(f"     STILL BAD after re-copy: {rel}")
            with open(quarantine, "a") as fh:
                fh.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M}\t{rel}\n")
    if checked:
        note = f", {repaired} repaired" if repaired else ""
        print(f"  verified {checked} new clip(s){note}")
    return unresolved


# Clips copied in this run, across all video folders; a disk map is drawn only
# when this is non-zero, so the idle 5-minute runs leave nothing behind.
copied_clips = 0

# Disk-map generator (sibling folder); writes disk-map-YYYYMMDD-HHMM.svg into
# Jazz-Dashcam/ after every run that copied clips.
DISK_MAP = Path(__file__).resolve().parent / "disk-map" / "disk-map.py"


def draw_disk_map() -> None:
    """Snapshot where the data sits on the HDD. Never fails the backup."""
    if TEST_MODE or not DISK_MAP.exists():
        return
    print("== Drawing disk map")
    try:
        r = subprocess.run([sys.executable, str(DISK_MAP)], capture_output=True,
                           text=True, timeout=600)
        out = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        print(f"  {out}" if r.returncode == 0 else
              f"  disk map failed (exit {r.returncode}): {r.stderr.strip()[-300:]}")
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  disk map failed: {e}")


def backup_videos(src: Path, dest: Path, staged: bool = False) -> list[str]:
    global copied_clips
    failed = []
    pruned_file = dest / PRUNED_LIST
    for dirname in VIDEO_DIRS:
        src_dir = src / dirname
        if not src_dir.is_dir():
            continue
        print(f"-- {dirname}/")
        # -a: archive, -u: skip files that already exist in the backup
        # (unless the card's copy is newer). --modify-window=2 absorbs the
        # FAT filesystem's 2-second mtime granularity so unchanged files
        # aren't re-copied. rsync copies via a temp file and renames on
        # success, so an interrupted run never leaves a partial .MP4 behind.
        cmd = ["rsync", "-au", "--modify-window=2", "--info=name1,stats1"]
        # rsync temp files (.NAME.XXXXXX) left by a killed stager or another
        # copier must never reach the archive; the camera writes no dotfiles
        cmd += ["--exclude", ".*"]
        if pruned_file.exists() and dirname not in PRUNE_PROTECTED:
            cmd += ["--exclude-from", str(pruned_file)]
        cmd += [f"{src_dir}/", f"{dest / dirname}/"]
        # Stream rsync's output rather than capturing it: a first-time backup
        # runs for hours and the cron log has to show progress as it happens.
        # --info=name1 names each transferred file, so collect those on the way
        # past and probe them below, while the card is still mounted.
        names = []
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            sys.stdout.write(line)
            stripped = line.strip()
            if stripped.upper().endswith(".MP4"):
                names.append(stripped)
        proc.stdout.close()
        copied_clips += len(names)
        if proc.wait() != 0:
            failed.append(f"{dirname}/ — not everything was copied (rsync exit code {proc.returncode})")
            continue
        for rel in verify_copied(src_dir, dest / dirname, names,
                                 dest / CORRUPT_LIST):
            failed.append(f"{dirname}/{rel} — copied, but unreadable even after re-copy (see {CORRUPT_LIST})")
    return failed


def verify_archive(dest: Path) -> list[str]:
    """Probe every clip already in the backup. For --verify-all."""
    bad = []
    for dirname in VIDEO_DIRS:
        d = dest / dirname
        if not d.is_dir():
            continue
        clips = sorted(p for p in d.rglob("*") if p.suffix.upper() == ".MP4")
        print(f"-- {dirname}/ ({len(clips)} clips)")
        for i, clip in enumerate(clips, 1):
            if not clip_readable(clip):
                rel = clip.relative_to(dest)
                bad.append(str(rel))
                print(f"  !! unreadable: {rel}")
            if i % 500 == 0:
                print(f"  ... {i}/{len(clips)}")
    return bad


def gps_timestamp(line: str) -> int:
    """Unix timestamp of a GPS record, 0 if invalid/no-fix/header."""
    try:
        return int(line.split(",", 1)[0])
    except ValueError:
        return 0


def first_fix_timestamp(data: bytes) -> int:
    """Timestamp of the first valid fix in a GPS file, 0 if none."""
    for line in data.decode(errors="replace").splitlines():
        ts = gps_timestamp(line)
        if ts > 0:
            return ts
    return 0


def update_gps(src: Path, gps_dir: Path) -> None:
    gps_dir.mkdir(parents=True, exist_ok=True)
    for gps_file in sorted(src.glob("GPSData*.txt")):
        data = gps_file.read_bytes()
        ts = first_fix_timestamp(data)
        if ts == 0:
            print(f"  {gps_file.name}: no valid fix yet, skipped")
            continue
        stamp = datetime.datetime.fromtimestamp(ts).strftime("%Y%m%d-%H%M%S")
        target = gps_dir / f"GPSData-{stamp}.txt"

        # Same card re-inserted: its file only ever grows, so the new copy
        # starts with the old snapshot's bytes and replaces it. Anything
        # else on the same name (e.g. the camera wrapped its log) is kept
        # as a separate file rather than overwritten.
        if target.exists():
            old = target.read_bytes()
            if old == data:
                print(f"  {gps_file.name}: unchanged ({target.name})")
                continue
            if not data.startswith(old):
                n = 1
                while (alt := gps_dir / f"GPSData-{stamp}.{n}.txt").exists() \
                        and alt.read_bytes() != data:
                    n += 1
                target = alt
                if target.exists():
                    print(f"  {gps_file.name}: unchanged ({target.name})")
                    continue

        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        print(f"  {gps_file.name}: saved as {target.name} "
              f"({len(data.splitlines()) - 1} records)")


# ---------------------------------------------------------------- staging ---

def write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def card_id(src: Path) -> str:
    """The card's FAT volume id, so a re-inserted card resumes its own batch."""
    try:
        out = subprocess.run(["findmnt", "-no", "UUID", str(src)],
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        out = ""
    return out or "card"


def stager_running() -> bool:
    lock = STAGING_ROOT / STAGE_LOCK
    if not lock.exists():
        return False
    with open(lock) as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def staged_batches() -> list[tuple[Path, dict]]:
    """Batch folders with a readable state file, oldest first."""
    out = []
    if STAGING_ROOT.is_dir():
        for d in sorted(STAGING_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                st = read_json(d / BATCH_STATE)
                if st:
                    out.append((d, st))
    return out


def tree_bytes(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def last_change(d: Path) -> float:
    """Newest ctime in the batch (mtimes are the card's, so they don't help)."""
    return max((f.stat().st_ctime for f in d.rglob("*")), default=d.stat().st_ctime)


def remove_batch(bdir: Path) -> None:
    if bdir.parent != STAGING_ROOT or bdir.name.startswith("."):
        raise RuntimeError(f"refusing to delete {bdir}")
    shutil.rmtree(bdir)


class Prefixed:
    """Tag every line the stager writes, since it shares the backup's log."""

    def __init__(self, stream, tag: str):
        self.stream, self.tag, self.fresh = stream, tag, True

    def write(self, s: str) -> int:
        for part in s.splitlines(keepends=True):
            if self.fresh:
                self.stream.write(self.tag)
            self.stream.write(part)
            self.fresh = part.endswith("\n")
        self.stream.flush()
        return len(s)

    def flush(self) -> None:
        self.stream.flush()


def stage_card(src: Path, dest: Path) -> int:
    """Process A: copy the card's new clips into a batch on the NVMe.

    Exit codes: 0 done / nothing new / another stager is running,
    1 failed (card removed?), 3 not enough NVMe space.
    """
    try:
        STAGING_ROOT.mkdir(parents=True, exist_ok=True)
        lockf = open(STAGING_ROOT / STAGE_LOCK, "a")
    except OSError as e:
        print(f"[A] staging area unavailable ({e})")
        return 3
    # retry briefly: the backup's "is a stager running?" probe takes the lock
    # for a moment, and must not be mistaken for another stager
    for _ in range(25):
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.2)
    else:
        return 0                          # another stager has this card

    sys.stdout = Prefixed(sys.stdout, "[A] ")
    card = card_id(src)
    status_file = STAGING_ROOT / STAGE_STATUS

    def status(state: str, **extra) -> None:
        write_json(status_file, {"state": state, "card": card, "pid": os.getpid(),
                                 "time": time.time(), **extra})

    status("scanning")
    try:
        verify_source_device(src)
    except SystemExit as e:
        print(e)
        status("error")
        return 1

    # What is new: not in the archive, not pruned, not in another batch.
    pruned = load_pruned(dest)
    resume = None
    elsewhere = set()
    for d, st in staged_batches():
        if resume is None and st.get("state") == "copying" and st.get("card") == card:
            resume = d                    # this card's interrupted batch
        else:
            elsewhere.update(st.get("files", {}))
    files: dict[str, int] = {}
    try:
        for dirname in VIDEO_DIRS:
            sd = src / dirname
            if not sd.is_dir():
                continue
            for f in sd.rglob("*"):
                # dotfiles are some copier's half-written temp files, never clips
                if not f.is_file() or f.name.startswith(".") or f.name in pruned:
                    continue
                rel = str(f.relative_to(src))
                if rel not in elsewhere and not (dest / rel).exists():
                    files[rel] = f.stat().st_size
    except OSError as e:
        print(f"card read failed while scanning: {e}")
        status("error")
        return 1
    files = dict(sorted(files.items()))
    total = sum(files.values())

    if not files:
        if resume is not None:            # its clips all reached the HDD already
            st = read_json(resume / BATCH_STATE) or {}
            write_json(resume / BATCH_STATE, {**st, "state": "complete", "files": {}})
        print("nothing new on the card")
        status("nothing")
        return 0

    have = sum((resume / r).stat().st_size for r in files
               if resume is not None and (resume / r).is_file())
    need = (total - have) * STAGE_SPACE_FACTOR
    free = shutil.disk_usage(STAGING_ROOT).free
    if free < need:
        print(f"NVMe has {free / 1e9:.1f} GB free, needs {need / 1e9:.1f} GB "
              f"({STAGE_SPACE_FACTOR}x {(total - have) / 1e9:.1f} GB) "
              f"— leaving this card to the direct backup")
        status("nospace", bytes=total)
        return 3

    bdir = resume or STAGING_ROOT / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{card}"
    bdir.mkdir(exist_ok=True)
    state = {"card": card, "state": "copying", "files": files, "bytes": total,
             "started": time.time()}
    write_json(bdir / BATCH_STATE, state)
    status("copying", batch=bdir.name, bytes=total)
    print(f"== Staging {len(files)} files, {total / 1e9:.1f} GB -> {bdir}"
          + (" (resuming)" if resume else ""))

    listing = bdir / ".files.txt"
    listing.write_text("".join(r + "\n" for r in files))
    t0 = time.time()
    proc = subprocess.Popen(
        ["rsync", "-a", "--modify-window=2", "--info=name1", "--files-from",
         str(listing)]
        + ([f"--bwlimit={os.environ['DASHCAM_TEST_BWLIMIT']}"]
           if TEST_MODE and "DASHCAM_TEST_BWLIMIT" in os.environ else [])
        + [f"{src}/", f"{bdir}/"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        sys.stdout.write(line)
    proc.stdout.close()
    rc = proc.wait()
    for g in src.glob("GPSData*.txt"):
        try:
            shutil.copy2(g, bdir / g.name)
        except OSError as e:
            print(f"GPS file {g.name} not staged: {e}")
    if rc != 0:
        print(f"!! staging stopped (rsync exit {rc}) — card removed? "
              f"It resumes when the card is back.")
        status("error", batch=bdir.name)
        return 1

    # Size check against the card, then a decoder check while the card is
    # still here to re-read anything that came off it badly.
    try:
        short = [r for r, size in files.items()
                 if not (bdir / r).is_file() or (bdir / r).stat().st_size != size]
    except OSError:
        short = ["(card unreadable)"]
    if short:
        print(f"!! {len(short)} staged files do not match the card, e.g. {short[0]}")
        status("error", batch=bdir.name)
        return 1
    for dirname in VIDEO_DIRS:
        names = [r.split("/", 1)[1] for r in files if r.startswith(dirname + "/")]
        if names:
            verify_copied(src / dirname, bdir / dirname, names, dest / CORRUPT_LIST)

    dt = max(time.time() - t0, 1)
    copied = total - have
    state.update(state="complete", finished=time.time())
    write_json(bdir / BATCH_STATE, state)
    status("done", batch=bdir.name, bytes=total)
    print(f"staged {len(files)} files, {copied / 1e9:.1f} GB in {dt / 60:.1f} min "
          f"({copied / 1e6 / dt:.0f} MB/s) — card can be removed")
    return 0


# ----------------------------------------------------------------- backup ---

announced = False


def announce() -> None:
    """Timestamp the log, once per run, only when the run has work to do."""
    global announced
    if not announced:
        print(f"{datetime.datetime.now().astimezone():%A %d %B %Y %I:%M:%S %p %Z}")
        announced = True


def launch_stager(src: Path, dest: Path) -> float:
    started = time.time()
    with open(LOG_FILE, "a") as log:
        subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()),
                          "--stage", str(src), str(dest)],
                         stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    # give it the moment it needs to scan the card and say what it will do
    deadline = started + 120
    while time.time() < deadline:
        time.sleep(1)
        st = read_json(STAGING_ROOT / STAGE_STATUS)
        if st and st.get("time", 0) >= started and st.get("state") != "scanning":
            break
        if st and st.get("state") == "copying" and stager_running():
            break                         # an earlier stager is already on it
        if not stager_running() and time.time() - started > 10:
            break
    return started


def staged_incoming(dest: Path) -> int:
    """Bytes all staged batches will add, each clip counted once.

    Always recomputed from the batches and the archive, never remembered, so
    clips copied before a crash no longer count after it."""
    pruned = load_pruned(dest)
    sizes: dict[str, int] = {}
    for _, st in staged_batches():
        sizes.update(st.get("files", {}))
    return sum(size for rel, size in sizes.items()
               if Path(rel).name not in pruned and not (dest / rel).exists())


def clean_stale_parts(dest: Path) -> None:
    """Half-made timelapses and re-fetches left by a run that died.

    Only the backup creates these and only one backup runs at a time, so any
    found at start-up are leftovers. The originals are untouched by then."""
    stale = [f for d in VIDEO_DIRS if (dest / d).is_dir()
             for f in (dest / d).rglob("*")
             if f.is_file() and (".part." in f.name and is_timelapse(f)
                                 or f.name.endswith(".refetch"))]
    if stale:
        announce()
        for f in stale:
            f.unlink()
        print(f"== Removed {len(stale)} leftover part file(s) from an interrupted run")


def process_batch(bdir: Path, st: dict, dest: Path) -> tuple[list[str], bool]:
    """Move one staged batch to the HDD. Returns (failures, ok to continue)."""
    announce()
    files = st.get("files", {})
    print(f"== Staged batch {bdir.name}: {len(files)} files, "
          f"{sum(files.values()) / 1e9:.1f} GB")
    print(f"== Pruning old backups to fit {PRUNE_LIMIT_BYTES / 1e12:.3f} TB limit")
    prune_old_files(dest, staged_incoming(dest))
    print(f"== Backing up videos: {bdir} -> {dest}")
    failed = backup_videos(bdir, dest, staged=True)
    print(f"== Snapshotting GPS data into {dest / 'GPS'}/")
    update_gps(bdir, dest / "GPS")
    if any("rsync exit" in f for f in failed):
        print(f"  batch kept for the next run: {bdir}")
        return failed, False
    remove_batch(bdir)
    print(f"  staging batch removed")
    return failed, True


def salvage(bdir: Path, st: dict) -> dict:
    """Make an abandoned half-staged batch safe to move: keep readable clips
    only. Anything dropped is still on the card and is staged next time."""
    dropped = 0
    for f in list(bdir.rglob("*")):
        if f.is_file() and (f.name.startswith(".") and f.parent != bdir
                            or f.suffix.upper() == ".MP4" and not clip_readable(f)):
            f.unlink()
            dropped += 1
    kept = {r: s for r, s in st.get("files", {}).items() if (bdir / r).is_file()}
    print(f"== Batch {bdir.name} was left half-staged (card gone for "
          f"{ABANDONED_SECONDS // 60}+ min): moving its {len(kept)} complete clips"
          + (f", {dropped} partial file(s) dropped" if dropped else ""))
    st = {**st, "state": "complete", "files": kept, "salvaged": True}
    write_json(bdir / BATCH_STATE, st)
    return st


def direct_backup(src: Path, dest: Path, why: str) -> list[str]:
    """The old path: prune for the card, copy from it, snapshot its GPS."""
    announce()
    print(f"== {why} — copying straight from the card")
    print(f"== Pruning old backups to fit {PRUNE_LIMIT_BYTES / 1e12:.3f} TB limit")
    prune_old_files(dest, incoming_bytes(src, dest, load_pruned(dest)))
    print(f"== Backing up videos: {src} -> {dest}")
    failed = backup_videos(src, dest)
    print(f"== Snapshotting GPS data into {dest / 'GPS'}/")
    update_gps(src, dest / "GPS")
    return failed


def wait_for_stager(dest: Path) -> bool:
    """Prune for the card being staged, then wait until the stager finishes.
    False if it stopped making progress."""
    announce()
    print("== Card is being staged; pruning for it meanwhile")
    print(f"== Pruning old backups to fit {PRUNE_LIMIT_BYTES / 1e12:.3f} TB limit")
    prune_old_files(dest, staged_incoming(dest))
    print("== Waiting for staging to finish")
    size, since = -1, time.time()
    while stager_running():
        busy = [d for d, st in staged_batches() if st.get("state") == "copying"]
        if not busy:
            break                         # batch complete; stager is finishing up
        now_size = sum(tree_bytes(d) for d in busy)
        if now_size != size:
            size, since = now_size, time.time()
        elif time.time() - since > STAGE_STALL_SECONDS:
            print(f"!! staging made no progress for {STAGE_STALL_SECONDS // 60} min "
                  f"— leaving it; the next run checks again")
            return False
        time.sleep(10)
    return True


def run_backup(src: Path, dest: Path) -> list[str]:
    """Process B."""
    if not card_present(src) and not staged_batches():
        return []                         # idle: leave the HDD alone
    clean_stale_parts(dest)
    started = None
    if card_present(src):
        announce()
        started = launch_stager(src, dest)

    failed: list[str] = []
    waited = moved = False
    while True:
        batches = staged_batches()
        complete = [(d, st) for d, st in batches if st.get("state") == "complete"]
        if complete:
            more, ok = process_batch(*complete[0], dest)
            failed += more
            moved = True
            if not ok:
                break
            continue

        copying = [(d, st) for d, st in batches if st.get("state") == "copying"]
        if stager_running():
            if copying and not waited:
                waited = True
                if not wait_for_stager(dest):
                    break
                continue
            if waited:
                time.sleep(5)             # writing its final state
                continue
            break                         # still scanning after 2 min: next run

        here = card_present(src)
        if started is not None and here:
            st = read_json(STAGING_ROOT / STAGE_STATUS) or {}
            fresh = st.get("time", 0) >= started and st.get("card") == card_id(src)
            if fresh and st.get("state") in ("done", "nothing"):
                if moved:                 # its GPS came with the batch
                    break
                print(f"== Snapshotting GPS data into {dest / 'GPS'}/")
                update_gps(src, dest / "GPS")
            else:
                why = {"nospace": "Not enough NVMe space to stage"}.get(
                    st.get("state"), f"Staging did not finish ({st.get('state', 'no status')})"
                    if fresh else "Staging did not start")
                failed += direct_backup(src, dest, why)
            break

        current = card_id(src) if here else None
        stale = [(d, st) for d, st in copying if st.get("card") != current
                 and time.time() - last_change(d) > ABANDONED_SECONDS]
        if stale:
            announce()
            salvage(*stale[0])
            continue
        for d, _ in copying:
            announce()
            print(f"== Half-staged batch {d.name} kept — it resumes when the card "
                  f"is back (or moves on its own after {ABANDONED_SECONDS // 60} min)")
        break
    return failed


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    src = Path(args[0] if args else DEFAULT_SRC)
    dest = Path(args[1] if len(args) > 1 else DEFAULT_DEST)

    if "--verify-all" in flags:
        print(f"== Verifying every clip in {dest}")
        bad = verify_archive(dest)
        if bad:
            print(f"\n{len(bad)} unreadable clip(s):")
            for b in bad:
                print(f"  {b}")
            sys.exit(1)
        print("All clips readable.")
        return

    if "--stage" in flags:
        sys.exit(stage_card(src, dest))

    dest.mkdir(parents=True, exist_ok=True)
    failed = run_backup(src, dest)
    if copied_clips:
        draw_disk_map()
    if failed:
        print("Backup finished WITH ERRORS:")
        for f in failed:
            print(f"  {f}")
        sys.exit(1)
    if announced:
        print("Backup complete." if copied_clips or not any(
            st.get("state") == "copying" for _, st in staged_batches())
            else "Backup run ended — waiting for the card to finish staging.")


if __name__ == "__main__":
    main()
