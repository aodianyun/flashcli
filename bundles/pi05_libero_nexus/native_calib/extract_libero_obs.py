#!/usr/bin/env python3
"""Extract real LIBERO observations (2 views) for PI0.5 native FP8 calibration.

Usage: extract_libero_obs.py <ds_dir> <out_dir> [step]
  <ds_dir>  LeRobot v3 slice with:
              tasks.parquet, data-file-000.parquet, episodes-file-000.parquet,
              image-file-000.mp4 (observation.images.image),
              image2-file-000.mp4 (observation.images.image2)
  <out_dir> receives obs_XXXX/{image.rgb,image2.rgb,state.txt,prompt.txt}

Writes raw RGB8 256x256 frames. video_t = episode.from_timestamp + frame_index/fps.
Requires: pyarrow, ffmpeg.
"""
import os
import subprocess
import sys

import pyarrow.parquet as pq

W = H = 256
FPS = 10.0


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    ds, out = argv[1], argv[2]
    step = int(argv[3]) if len(argv) > 3 else 15

    tasks = pq.read_table(f"{ds}/tasks.parquet").to_pydict()
    task_map = dict(zip(tasks["task_index"], tasks["__index_level_0__"]))
    data = pq.read_table(f"{ds}/data-file-000.parquet").to_pydict()
    eps = pq.read_table(f"{ds}/episodes-file-000.parquet").to_pydict()

    from_ts = {}
    for i, e in enumerate(eps["episode_index"]):
        from_ts[e] = (
            float(eps["videos/observation.images.image/from_timestamp"][i]),
            float(eps["videos/observation.images.image2/from_timestamp"][i]),
        )
    vid_image = f"{ds}/image-file-000.mp4"
    vid_image2 = f"{ds}/image2-file-000.mp4"

    def grab(video, t):
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video,
             "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True, check=True,
        )
        if len(r.stdout) != W * H * 3:
            raise RuntimeError(f"frame bytes {len(r.stdout)} != {W*H*3} at t={t}")
        return r.stdout

    os.makedirs(out, exist_ok=True)
    n = 0
    for row in range(len(data["episode_index"])):
        e = int(data["episode_index"][row])
        f = int(data["frame_index"][row])
        if e not in tuple(from_ts):
            continue
        if f % step != 0:
            continue
        t0, t1 = from_ts[e]
        d = os.path.join(out, f"obs_{n:04d}")
        os.makedirs(d, exist_ok=True)
        open(f"{d}/image.rgb", "wb").write(grab(vid_image, t0 + f / FPS))
        open(f"{d}/image2.rgb", "wb").write(grab(vid_image2, t1 + f / FPS))
        state = data["observation.state"][row]
        open(f"{d}/state.txt", "w").write(",".join(f"{float(x):.6f}" for x in state))
        open(f"{d}/prompt.txt", "w").write(task_map[int(data["task_index"][row])])
        n += 1
    print(f"wrote {n} observations to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
