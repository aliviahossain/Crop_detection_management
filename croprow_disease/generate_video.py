"""Compile an image sequence into a browser-playable H.264 clip.

Optionally overlays the derived healthy/unhealthy labels, which makes this the
quickest way to see what the colour rule does across a whole sequence rather
than the still frames notebook 02 samples.

OpenCV cannot reliably encode H.264 on Windows (no bundled x264) and its default
`mp4v` fourcc produces MPEG-4 Part 2, which browsers refuse to play -- so frames
are piped to the ffmpeg that ships with imageio-ffmpeg and encoded libx264 +
yuv420p.

    python croprow_disease/generate_video.py <image_folder> [out.mp4] [--labels]

`--labels` draws boxes coloured by derived class (green = healthy, orange-red =
unhealthy). It needs LettuceMOTS polygon labels for that sequence, so it works
on train sequences only; test sequences have no labels and render unannotated.
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

FPS = 10  # adjust to the dataset's capture rate


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    draw_labels = "--labels" in sys.argv

    image_folder = args[0] if args else str(
        Path(os.environ.get("LETTUCE_ROOT", r"D:\croprow_dataset\LettuceMOTS"))
        / "test" / "images" / "0003")
    video_name = args[1] if len(args) > 1 else "croprow_health.mp4"

    images = sorted(glob.glob(os.path.join(image_folder, "*.png")))
    if not images:
        print(f"No images found in {image_folder}. Please check the path!")
        return 1

    try:
        import imageio_ffmpeg
    except ImportError:
        print("imageio-ffmpeg is required to encode H.264. Install it:\n"
              "    pip install imageio-ffmpeg")
        return 1

    U = root = None
    if draw_labels:
        from croprow_disease import utils as U  # noqa: F811
        lettuce_root = os.environ.get("LETTUCE_ROOT", r"D:\croprow_dataset\LettuceMOTS")
        root = U.resolve_lettuce_root(lettuce_root)
        print(f"drawing derived labels from {U.poly_labels_dir(root)}")

    # H.264 + yuv420p needs even dimensions; crop a stray odd row/column.
    first = cv2.imread(images[0])
    height, width = first.shape[:2]
    width -= width % 2
    height -= height % 2

    writer = imageio_ffmpeg.write_frames(
        video_name,
        (width, height),
        pix_fmt_in="rgb24",
        pix_fmt_out="yuv420p",
        fps=FPS,
        codec="libx264",
        macro_block_size=1,        # dims are already even; do not auto-pad
        output_params=["-movflags", "+faststart"],
    )
    writer.send(None)  # seed the generator

    print(f"Compiling {len(images)} frames -> {video_name} (H.264)...")
    n_labelled = 0
    for image_path in images:
        frame = cv2.imread(image_path)  # BGR
        if frame is None:
            continue
        frame = frame[:height, :width]
        if draw_labels:
            inst = U.instances_for_image(root, Path(image_path))
            if inst:
                frame = U.draw_instances(frame, inst)
                n_labelled += 1
        writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes())

    writer.close()
    print(f"Success! Browser-playable video saved as {video_name}")
    if draw_labels:
        print(f"  {n_labelled}/{len(images)} frames had labels to draw"
              + ("  (0 = this is probably a test sequence, which has none)"
                 if n_labelled == 0 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
