"""Record the classroom replay as an animated GIF: one headless Chrome screenshot per 5-minute step, joined by Pillow.

    python make_gif.py                      # 08:00-17:30, Korean labels -> video/classroom_<day>.gif (git ignored)
    python make_gif.py --lang en --every 2  # English, every 2nd step

No ffmpeg needed. For an MP4, run ffmpeg on video/frames/*.png (not done here: ffmpeg is not installed).
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
CHROME = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
          Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--start", default="08:00")
    ap.add_argument("--end", default="17:30")
    ap.add_argument("--size", default="1280,800")
    a = ap.parse_args()
    data = json.loads(re.search(r"=\s*(\{.*\});", (HERE / "classroom_data.js").read_text(encoding="utf-8"), re.S).group(1))
    times = data["times"]
    steps = range(times.index(a.start), times.index(a.end) + 1, a.every)
    browser = next(p for p in CHROME if p.exists())
    frames = HERE / "video" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    shots = []
    for i in steps:
        out = frames / f"{a.lang}_{i:03d}.png"
        url = (HERE / "index.html").as_uri() + f"?still=1&t={i}&lang={a.lang}"
        subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={a.size}",
                        "--force-device-scale-factor=1", "--virtual-time-budget=2000", f"--screenshot={out}", url],
                       check=True, capture_output=True, timeout=60)
        assert out.exists() and out.stat().st_size > 0, f"no screenshot for step {i}"
        shots.append(out)
        print(times[i], end=" ", flush=True)
    imgs = [Image.open(p).convert("P", palette=Image.ADAPTIVE, colors=128) for p in shots]
    gif = HERE / "video" / f"classroom_{data['day']}_{a.lang}.gif"
    imgs[0].save(gif, save_all=True, append_images=imgs[1:], duration=180, loop=0, optimize=True)
    print("\nwrote", gif, f"({len(imgs)} frames)")


if __name__ == "__main__":
    main()
