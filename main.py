#!/usr/bin/env python3
"""Mock generator: composites a video clip as a GIF into a device mockup template."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageSequence

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_FILE = TEMPLATES_DIR / "templates.json"
OUTPUT_DIR = Path(__file__).parent / "output"


def load_templates() -> dict:
    with open(TEMPLATES_FILE) as f:
        return json.load(f)


def save_templates(templates: dict):
    with open(TEMPLATES_FILE, "w") as f:
        json.dump(templates, f, indent=2)


def require_ffmpeg():
    if not shutil.which("ffmpeg"):
        sys.exit("Error: ffmpeg not found. Install it with: brew install ffmpeg")


def video_to_frames(video_path: str, fps: int, max_seconds: float, tmpdir: str) -> list[Image.Image]:
    """Extract frames from video using ffmpeg, return list of PIL Images."""
    frames_pattern = os.path.join(tmpdir, "frame_%04d.png")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps={fps}",
        "-t", str(max_seconds),
        "-q:v", "2",
        frames_pattern,
        "-y", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    frame_files = sorted(Path(tmpdir).glob("frame_*.png"))
    if not frame_files:
        sys.exit("Error: ffmpeg produced no frames. Check your video file.")
    return [Image.open(f).convert("RGBA") for f in frame_files]


def composite_frames(frames: list[Image.Image], template: dict) -> list[Image.Image]:
    """Resize and composite each frame onto the mockup image using the mask."""
    mockup_path = TEMPLATES_DIR / template["image"]
    mask_path = TEMPLATES_DIR / template["mask"]
    region = template["region"]  # [x1, y1, x2, y2]

    mockup = Image.open(mockup_path).convert("RGBA")
    mask = Image.open(mask_path).convert("L")

    x1, y1, x2, y2 = region
    region_w = x2 - x1
    region_h = y2 - y1

    composited = []
    for frame in frames:
        base = mockup.copy()
        resized = frame.resize((region_w, region_h), Image.LANCZOS)
        # Crop mask to region size and use as alpha for the video frame
        region_mask = mask.crop((x1, y1, x2, y2)).resize((region_w, region_h), Image.LANCZOS)
        resized.putalpha(region_mask)
        base.paste(resized, (x1, y1), resized)
        composited.append(base.convert("RGB"))

    return composited


def save_gif(frames: list[Image.Image], output_path: str, fps: int):
    delay = int(1000 / fps)
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=delay,
        optimize=False,
    )
    print(f"Saved: {output_path}")


# --- CLI commands ---

def cmd_generate(args):
    require_ffmpeg()
    templates = load_templates()
    if args.template not in templates:
        sys.exit(f"Error: template '{args.template}' not found. Run `template list` to see available templates.")

    template = templates[args.template]
    for key in ("image", "mask", "region"):
        if key not in template:
            sys.exit(f"Error: template '{args.template}' is missing field '{key}'.")

    output_path = args.output or str(OUTPUT_DIR / f"{Path(args.video).stem}_{args.template}.gif")

    print(f"Extracting frames at {args.fps}fps (max {args.duration}s)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        frames = video_to_frames(args.video, args.fps, args.duration, tmpdir)
        print(f"Compositing {len(frames)} frames onto '{args.template}' mockup...")
        composited = composite_frames(frames, template)

    save_gif(composited, output_path, args.fps)


def cmd_template_add(args):
    templates = load_templates()
    if args.name in templates and not args.force:
        sys.exit(f"Error: template '{args.name}' already exists. Use --force to overwrite.")

    for path in (args.image, args.mask):
        if not Path(path).exists():
            sys.exit(f"Error: file not found: {path}")

    # Copy assets into templates dir
    image_dest = TEMPLATES_DIR / Path(args.image).name
    mask_dest = TEMPLATES_DIR / Path(args.mask).name
    shutil.copy2(args.image, image_dest)
    shutil.copy2(args.mask, mask_dest)

    templates[args.name] = {
        "image": Path(args.image).name,
        "mask": Path(args.mask).name,
        "region": args.region,
    }
    save_templates(templates)
    print(f"Template '{args.name}' added.")


def cmd_template_edit(args):
    templates = load_templates()
    if args.name not in templates:
        sys.exit(f"Error: template '{args.name}' not found.")

    t = templates[args.name]
    if args.region:
        t["region"] = args.region
    if args.image:
        if not Path(args.image).exists():
            sys.exit(f"Error: file not found: {args.image}")
        dest = TEMPLATES_DIR / Path(args.image).name
        shutil.copy2(args.image, dest)
        t["image"] = Path(args.image).name
    if args.mask:
        if not Path(args.mask).exists():
            sys.exit(f"Error: file not found: {args.mask}")
        dest = TEMPLATES_DIR / Path(args.mask).name
        shutil.copy2(args.mask, dest)
        t["mask"] = Path(args.mask).name

    save_templates(templates)
    print(f"Template '{args.name}' updated.")


def cmd_template_list(args):
    templates = load_templates()
    if not templates:
        print("No templates defined yet.")
        return
    for name, t in templates.items():
        region = t.get("region", "?")
        print(f"  {name}: image={t.get('image')}  mask={t.get('mask')}  region={region}")


def cmd_template_remove(args):
    templates = load_templates()
    if args.name not in templates:
        sys.exit(f"Error: template '{args.name}' not found.")
    del templates[args.name]
    save_templates(templates)
    print(f"Template '{args.name}' removed.")


# --- Argument parsing ---

def main():
    parser = argparse.ArgumentParser(description="Device mockup GIF generator")
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    gen = sub.add_parser("generate", help="Generate a mockup GIF from a video")
    gen.add_argument("--video", required=True, help="Path to input video file")
    gen.add_argument("--template", required=True, help="Template name to use")
    gen.add_argument("--output", help="Output GIF path (default: output/<name>.gif)")
    gen.add_argument("--fps", type=int, default=15, help="GIF frame rate (default: 15)")
    gen.add_argument("--duration", type=float, default=5.0, help="Max seconds to capture (default: 5)")
    gen.set_defaults(func=cmd_generate)

    # template
    tmpl = sub.add_parser("template", help="Manage templates")
    tmpl_sub = tmpl.add_subparsers(dest="subcommand", required=True)

    t_add = tmpl_sub.add_parser("add", help="Add a new template")
    t_add.add_argument("--name", required=True)
    t_add.add_argument("--image", required=True, help="Path to mockup still image")
    t_add.add_argument("--mask", required=True, help="Path to B&W mask PNG (white = screen area)")
    t_add.add_argument("--region", required=True, nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    t_add.add_argument("--force", action="store_true", help="Overwrite if template already exists")
    t_add.set_defaults(func=cmd_template_add)

    t_edit = tmpl_sub.add_parser("edit", help="Edit an existing template")
    t_edit.add_argument("--name", required=True)
    t_edit.add_argument("--image", help="Replace mockup image")
    t_edit.add_argument("--mask", help="Replace mask image")
    t_edit.add_argument("--region", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    t_edit.set_defaults(func=cmd_template_edit)

    t_list = tmpl_sub.add_parser("list", help="List all templates")
    t_list.set_defaults(func=cmd_template_list)

    t_remove = tmpl_sub.add_parser("remove", help="Remove a template")
    t_remove.add_argument("--name", required=True)
    t_remove.set_defaults(func=cmd_template_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
