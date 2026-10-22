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

Usage: python3 backup-dashcam.py [source_mount] [dest_dir]
       python3 backup-dashcam.py --verify-all   # probe every clip already backed up
"""

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_SRC = "/media/surya/70MAI"
DEFAULT_DEST = "/media/surya/Surya_HDD_5/Jazz-Dashcam/70mai"
VIDEO_DIRS = ["Normal", "Event", "Parking", "Lapse", "Photo"]
# Storage cap for the whole backup directory, GPS/ and existing timelapses
# included (those are never pruned, but they count). Before copying, the
# oldest recordings are pruned until the incoming files fit.
PRUNE_LIMIT_BYTES = 1_250_000_000_000  # 1.25 TB
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


def verify_source_device(src: Path) -> None:
    if not os.path.ismount(src):
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
            if not f.is_file() or f.name in pruned:
                continue
            dest_file = dest / f.relative_to(src)
            if not dest_file.exists():
                total += f.stat().st_size
    return total


def prune_old_files(src: Path, dest: Path, limit: int = PRUNE_LIMIT_BYTES) -> None:
    """Delete oldest non-Event recordings from the backup until the files
    about to be copied fit under the storage limit."""
    pruned_file = dest / PRUNED_LIST
    pruned = set(pruned_file.read_text().split()) if pruned_file.exists() else set()

    existing = prunable_backup_files(dest)
    used = total_backup_bytes(dest)
    needed = incoming_bytes(src, dest, pruned)
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
            f.unlink()
            plog.write(f.name + "\n")
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
            f.unlink()
            plog.write(f.name + "\n")
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
    if not DISK_MAP.exists():
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


def backup_videos(src: Path, dest: Path) -> list[str]:
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
            failed.append(f"{dirname}/ (rsync exit code {proc.returncode})")
            continue
        for rel in verify_copied(src_dir, dest / dirname, names,
                                 dest / CORRUPT_LIST):
            failed.append(f"{dirname}/{rel} (unreadable even after re-copy)")
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

    if not src.is_dir():
        sys.exit(f"ERROR: source '{src}' not found — is the SD card mounted?")
    verify_source_device(src)
    dest.mkdir(parents=True, exist_ok=True)

    print(f"== Pruning old backups to fit {PRUNE_LIMIT_BYTES / 1e12:.3f} TB limit")
    prune_old_files(src, dest)
    print(f"== Backing up videos: {src} -> {dest}")
    failed = backup_videos(src, dest)
    print(f"== Snapshotting GPS data into {dest / 'GPS'}/")
    update_gps(src, dest / "GPS")
    if copied_clips:
        draw_disk_map()

    if failed:
        print("Backup finished WITH ERRORS — these files could not be copied:")
        for f in failed:
            print(f"  {f}")
        sys.exit(1)
    print("Backup complete.")


if __name__ == "__main__":
    main()
