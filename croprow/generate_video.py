"""Compile a LettuceMOTS image sequence into a browser-playable H.264 clip.

The old version wrote MPEG-4 Part 2 (cv2 fourcc 'mp4v'), which browsers cannot
decode -- the CropRow lab's "Upload video" would load its duration but never
show a frame. OpenCV cannot reliably encode H.264 on Windows (no bundled x264),
so we pipe frames to the ffmpeg that ships with imageio-ffmpeg and encode
libx264 + yuv420p, which every browser plays.

    python croprow/generate_video.py                       # defaults below
    python croprow/generate_video.py <image_folder> [out.mp4]
"""
import glob
import os
import sys

import cv2

# Defaults; override with CLI args. Point at a LettuceMOTS sequence of PNG frames.
image_folder = sys.argv[1] if len(sys.argv) > 1 else r'D:\download\LettuceMOTS\test\images\0007'
video_name = sys.argv[2] if len(sys.argv) > 2 else 'output_video.mp4'
fps = 10  # adjust to the dataset's capture rate

images = sorted(glob.glob(os.path.join(image_folder, '*.png')))
if not images:
    print(f"No images found in {image_folder}. Please check the path!")
    sys.exit(1)

try:
    import imageio_ffmpeg
except ImportError:
    print(
        "imageio-ffmpeg is required to encode H.264. Install it:\n"
        "    pip install imageio-ffmpeg"
    )
    sys.exit(1)

# H.264 + yuv420p needs even dimensions; crop a stray odd row/column if present.
first = cv2.imread(images[0])
height, width = first.shape[:2]
width -= width % 2
height -= height % 2

writer = imageio_ffmpeg.write_frames(
    video_name,
    (width, height),
    pix_fmt_in="rgb24",
    pix_fmt_out="yuv420p",
    fps=fps,
    codec="libx264",
    macro_block_size=1,  # dims are already even; do not auto-pad
    output_params=["-movflags", "+faststart"],
)
writer.send(None)  # seed the generator

print(f"Compiling {len(images)} frames -> {video_name} (H.264)...")
for image_path in images:
    frame = cv2.imread(image_path)  # BGR
    if frame is None:
        continue
    frame = frame[:height, :width]
    # Optional: parse the LettuceMOTS label files (.txt) here and draw boxes
    # with cv2.rectangle() before writing.
    writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes())

writer.close()
print(f"Success! Browser-playable video saved as {video_name}")
