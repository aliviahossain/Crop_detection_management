"""Transcode croprow_disease demo clips to browser-playable H.264.

Clips written by cv2's default `mp4v` fourcc (including notebook 06's annotated
output) are MPEG-4 Part 2, which browsers cannot decode -- a video upload loads
the file's duration but never renders a frame. This rewrites them as H.264 +
yuv420p, which every browser plays.

Usage (run in any env; ffmpeg comes bundled via imageio-ffmpeg):

    python croprow_disease/convert_videos.py                  # runs/ -> demo_clips/
    python croprow_disease/convert_videos.py <src>            # a file or folder of .mp4
    python croprow_disease/convert_videos.py <src> <out_dir>  # write elsewhere

<src> may be one .mp4 or a folder; <out_dir> is created if missing. Originals
are left untouched.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "demo_clips"
# Notebook 06 writes its annotated output here.
DEFAULT_SRC = HERE / "runs"


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        # Fall back to a system ffmpeg if the helper package is not installed.
        return "ffmpeg"


def _inputs(arg: str | None) -> list[Path]:
    target = Path(arg) if arg else DEFAULT_SRC
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.mp4"))
    print(f"Nothing to convert at {target}.")
    return []


def convert(ffmpeg: str, src: Path, out_dir: Path) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{src.stem}_h264.mp4"
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        print(f"skip  {src.name} (already converted)")
        return True
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-movflags", "+faststart", "-an", str(dest),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)
    if proc.returncode != 0:
        print(f"FAIL  {src.name}\n{proc.stdout[-800:]}")
        return False
    print(f"ok    {src.name} -> {dest}")
    return True


def main() -> int:
    ffmpeg = _ffmpeg()
    srcs = [s for s in _inputs(sys.argv[1] if len(sys.argv) > 1 else None)
            if not s.stem.endswith("_h264")]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not srcs:
        return 1
    ok = sum(convert(ffmpeg, s, out_dir) for s in srcs)
    print(f"\nConverted {ok}/{len(srcs)} clip(s) into {out_dir}.")
    return 0 if ok == len(srcs) else 1


if __name__ == "__main__":
    sys.exit(main())
