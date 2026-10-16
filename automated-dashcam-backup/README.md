# Automated dashcam backup

Backs up a 70mai A500S dashcam SD card to an HDD whenever the card is plugged
in, keeps the archive under a size limit, and verifies what it copied.

## What it does, in order

1. **Checks the card is the dashcam's.** It looks for the camera's marker file
   `.used.file.DR2500` at the card root and refuses to run without it.
2. **Prunes, if needed.** If `70mai/` plus the incoming files would exceed
   `PRUNE_LIMIT_BYTES` (1.2 TB), the oldest recordings are converted to 1 fps
   timelapses (`TL-<name>.MP4`, about 10x smaller) and the originals deleted,
   oldest first, until it fits.
   * The limit is measured against the **whole** `70mai/` directory, Event/ and
     GPS/ included.
   * `Event/` is never deleted, and existing `TL-` files are never deleted.
     Both count against the limit, so the script warns if it is asked to free
     more than is deletable.
   * Pruned names go to `pruned.txt`, so a file still on the card is never
     copied back in.
3. **Copies the videos.** `rsync -au` of `Normal/ Event/ Parking/ Lapse/ Photo/`.
4. **Verifies every copied clip** with `ffprobe`. A clip that will not open is
   re-fetched from the card (up to 3 attempts) into a `.refetch` file and only
   renamed into place once it verifies. Clips that still fail are logged in
   `corrupt.txt`.
5. **Snapshots the GPS log.** `GPSData*.txt` is copied verbatim into `GPS/`,
   named by the timestamp of its first valid fix, so cards backed up in any
   order never overwrite each other.

## Usage

```bash
python3 backup-dashcam.py [source_mount] [dest_dir]
python3 backup-dashcam.py --verify-all     # probe every clip already in the archive
```

Defaults are set at the top of the script:

| | |
|---|---|
| `DEFAULT_SRC` | `/media/surya/70MAI` |
| `DEFAULT_DEST` | `/media/surya/Surya_HDD_5/Jazz-Dashcam/70mai` |
| `PRUNE_LIMIT_BYTES` | `1_200_000_000_000` (1.2 TB) |

Needs `python3` (3.10+), `rsync` and `ffmpeg`/`ffprobe`.

## Running it automatically

A cron entry fires every 5 minutes. It only does anything when the card is
mounted, and `flock -n` makes sure two runs never overlap: a long prune holds
the lock and later firings exit immediately.

```cron
*/5 * * * * mountpoint -q /media/surya/70MAI && { date; flock -n /tmp/jazz-dashcam-backup.lock python3 -u "/media/surya/Surya_HDD_5/Jazz-Dashcam/scripts/backup-dashcam.py"; } >> "/media/surya/Surya_HDD_5/Jazz-Dashcam/scripts/backup.log" 2>&1
```

## Sizing the limit

On a 1.5 TB drive the usable space is about 1,400 GB: ext4 metadata takes
~25 GB and the default 5% root reserve another ~75 GB. The limit is 1.2 TB,
which leaves ~190 GB free; 1.35 TB (~40 GB free) was used before.

Keep the 5% reserve. The archive drive is a Seagate Expansion Portable, which
is SMR: as it nears full its writes collapse to a few MB/s (seen at 90% full,
2026-10-16). Cutting the reserve to 1% to raise the limit to 1.4 TB was tried
and reverted. After a rest the drive takes roughly 25 GB at full speed (~85
MB/s), then drops to 3-20 MB/s. Its USB bridge does not pass TRIM, so the
drive never learns that pruned files were freed.

## Things learned the hard way

* **A missing day shows up as GPS fixes with zero clips.** If the card sits
  out of the PC for days, nothing in the log says so: cron logs nothing when
  the card is absent. Cross-check the GPS log against the clip count per date.
* **The camera moves clips into `Event/`, it does not copy them.** Anything
  that reads footage must look in both `Normal/` and `Event/`.
* **`rsync` read errors are not card death.** Transient I/O errors on a couple
  of files cleared on the next run; rsync's own checksum discarded the bad
  copies rather than writing them.
* **A corrupt clip can make ffmpeg exit 0** while silently dropping frames,
  hence the `ffprobe` verification after every copy.
* **`TL-` files keep the source clip's mtime.** Use `ctime` to see when the
  prune actually wrote them.
* **The prune is sequential**, one ffmpeg at a time. x264's own threading is
  why a single encode shows ~200% CPU.
* **A `dd` stuck on a dying card ignores Ctrl-C and `kill -9`.** It sits in
  uninterruptible sleep; offline the device instead:
  `echo offline | sudo tee /sys/block/sdX/device/state`.
* **Don't use `pgrep -f`/`pkill -f backup-dashcam`** from a shell whose own
  command line contains that string: it matches itself.
