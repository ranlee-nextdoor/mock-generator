import io
import os
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, url_for
from PIL import Image
from werkzeug.utils import secure_filename

import figma as figma_api
from main import save_gif, video_to_frames

app = Flask(__name__, template_folder="templates_html")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm", "mkv"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def file_ext(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def is_video(filename):
    return file_ext(filename) in VIDEO_EXTENSIONS


def is_image(filename):
    return file_ext(filename) in IMAGE_EXTENSIONS


def center_crop_to_square(img: Image.Image) -> Image.Image:
    """Center-crop an image to a square."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def fit_media_to_region(img: Image.Image, region_w: int, region_h: int) -> Image.Image:
    """
    Fit media into the target region:
    - If region is square (1:1): center-crop media to square first, then resize.
    - If region is non-square: center-crop media to match region aspect ratio, then resize.
    """
    img = img.convert("RGBA")
    src_w, src_h = img.size
    target_ratio = region_w / region_h
    src_ratio = src_w / src_h

    if abs(src_ratio - target_ratio) > 0.01:
        # Crop to match target aspect ratio
        if src_ratio > target_ratio:
            # Source is wider — crop sides
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            # Source is taller — crop top/bottom
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))

    return img.resize((region_w, region_h), Image.LANCZOS)


def scale_region(region: dict, scale: float) -> dict:
    return {k: int(v * scale) for k, v in region.items()}


def build_frame(
    media_frame: Image.Image,
    mockup: Image.Image,
    logo_img: Image.Image | None,
    variant_config: dict,
) -> Image.Image:
    """Composite one media frame into the mockup at the correct region."""
    # Scale factor: Figma exports at 2x by default
    comp_w = variant_config["component"]["width"]
    export_scale = mockup.width / comp_w

    media_region = variant_config.get("media_region")
    logo_region = variant_config.get("logo_region")

    # Punch a transparent hole in the mockup where the media goes
    chrome = mockup.copy().convert("RGBA")
    if media_region:
        r = scale_region(media_region, export_scale)
        # Clear the media placeholder area to transparent
        chrome.paste((0, 0, 0, 0), (r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"]))

    # Build composite: white base → media → mockup chrome (with hole) → logo
    result = Image.new("RGBA", mockup.size, (255, 255, 255, 255))

    if media_region:
        r = scale_region(media_region, export_scale)
        fitted = fit_media_to_region(media_frame, r["width"], r["height"])
        result.paste(fitted.convert("RGBA"), (r["x"], r["y"]))

    # Paste chrome (mockup with transparent media hole) on top
    result.alpha_composite(chrome)

    if logo_img and logo_region:
        r = scale_region(logo_region, export_scale)
        logo = logo_img.convert("RGBA").resize((r["width"], r["height"]), Image.LANCZOS)
        result.alpha_composite(logo, (r["x"], r["y"]))

    final = result.convert("RGB")
    # Resize output to 400px wide to reduce file size and memory
    target_w = 400
    if final.width > target_w:
        scale = target_w / final.width
        final = final.resize((target_w, int(final.height * scale)), Image.LANCZOS)
    return final


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(Path(__file__).parent / "static", filename)


@app.route("/")
def index():
    devices = figma_api.get_available_devices()
    formats = figma_api.get_available_formats()
    format_specs = figma_api.FORMAT_SPECS
    return render_template("index.html", devices=devices, formats=formats, format_specs=format_specs)


@app.route("/api/debug")
def debug():
    import figma as f
    token = os.environ.get("FIGMA_TOKEN")
    file_key = os.environ.get("FIGMA_FILE_KEY", "WRPoyXiU5wyxxTOYt9WZsF")
    variant = f.get_variant_config("web", "image_1_1")
    result = {"token_set": bool(token), "token_prefix": token[:8] if token else None, "file_key": file_key, "variant_config": variant}
    if variant:
        try:
            url_resp = f.export_component_png.__wrapped__ if hasattr(f.export_component_png, '__wrapped__') else None
            import requests
            r = requests.get(f"https://api.figma.com/v1/images/{file_key}", headers={"X-Figma-Token": token}, params={"ids": variant["node_id"], "format": "png", "scale": 1}, timeout=15)
            result["figma_api_status"] = r.status_code
            result["figma_api_response"] = r.json()
        except Exception as e:
            result["figma_api_error"] = str(e)
    return jsonify(result)


@app.route("/api/frame")
def api_frame():
    device = request.args.get("device", "web")
    format_key = request.args.get("format", "image_1_1")
    variant = figma_api.get_variant_config(device, format_key)
    if not variant:
        return jsonify({"error": "Not found"}), 404
    # Return proxied URL so the browser doesn't hit CORS on the Figma S3 URL
    proxy_url = url_for("frame_image", device=device, format=format_key)
    return jsonify({
        "frame_url": proxy_url,
        "component": variant["component"],
        "media_region": variant["media_region"],
        "logo_region": variant["logo_region"],
    })


@app.route("/api/frame-image")
def frame_image():
    """Proxy the Figma frame PNG, optionally with the media region punched out to transparent."""
    device = request.args.get("device", "web")
    format_key = request.args.get("format", "image_1_1")
    punch = request.args.get("punch", "0") == "1"
    variant = figma_api.get_variant_config(device, format_key)
    if not variant:
        return "Not found", 404
    png_bytes = figma_api.export_component_png(variant["node_id"])
    if not png_bytes:
        return "Failed to fetch from Figma", 502

    if punch and variant.get("media_region"):
        # Punch the media region transparent so client-side canvas can draw video through it
        mockup = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        comp_w = variant["component"]["width"]
        export_scale = mockup.width / comp_w
        mr = variant["media_region"]
        r = scale_region(mr, export_scale)
        mockup.paste((0, 0, 0, 0), (r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"]))
        buf = io.BytesIO()
        mockup.save(buf, format="PNG")
        png_bytes = buf.getvalue()

    return png_bytes, 200, {"Content-Type": "image/png", "Cache-Control": "public, max-age=300"}


@app.route("/api/format-spec/<format_key>")
def format_spec(format_key):
    spec = figma_api.get_format_spec(format_key)
    if not spec:
        return jsonify({"error": "Unknown format"}), 404
    return jsonify(spec)


@app.route("/generate", methods=["POST"])
def generate():
    device_key = request.form.get("device")
    format_key = request.form.get("format")
    headline = request.form.get("headline", "")
    body = request.form.get("body", "")
    cta = request.form.get("cta", "")
    fps = min(int(request.form.get("fps", 10)), 12)      # cap at 12fps
    duration = min(float(request.form.get("duration", 3)), 4.0)  # cap at 4s

    spec = figma_api.get_format_spec(format_key)
    if not spec:
        return jsonify({"error": "Invalid format"}), 400

    media_file = request.files.get("media")
    logo_file = request.files.get("logo")

    if not media_file:
        return jsonify({"error": "No media file uploaded"}), 400

    # Validate character limits
    errors = []
    if spec["headline_limit"] and len(headline) > spec["headline_limit"]:
        errors.append(f"Headline exceeds {spec['headline_limit']} characters")
    if spec["body_limit"] and body and len(body) > spec["body_limit"]:
        errors.append(f"Body exceeds {spec['body_limit']} characters")
    if spec["cta_limit"] and cta and len(cta) > spec["cta_limit"]:
        errors.append(f"CTA exceeds {spec['cta_limit']} characters")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    # Get the specific Figma variant for this device + format combo (export at 1x to save memory)
    variant_config = figma_api.get_variant_config(device_key, format_key)
    mockup_bytes = figma_api.export_component_png(variant_config["node_id"], scale=1.0) if variant_config else None

    output_filename = uuid.uuid4().hex

    with tempfile.TemporaryDirectory() as tmpdir:
        media_path = os.path.join(tmpdir, secure_filename(media_file.filename))
        media_file.save(media_path)

        logo_img = None
        if logo_file and logo_file.filename:
            logo_img = Image.open(logo_file).convert("RGBA")

        if is_video(media_file.filename):
            frames = video_to_frames(media_path, fps, duration, tmpdir)
            mockup = Image.open(io.BytesIO(mockup_bytes)).convert("RGBA") if mockup_bytes else None
            composited = []
            for f in frames:
                frame = build_frame(f, mockup, logo_img, variant_config) if mockup and variant_config else f.convert("RGB")
                composited.append(frame)
                del f  # free raw frame immediately
            out_path = str(OUTPUT_DIR / f"{output_filename}.gif")
            save_gif(composited, out_path, fps)
            del composited  # free after save
            download_name = "mockup.gif"

        elif is_image(media_file.filename):
            media_img = Image.open(media_path).convert("RGBA")
            if mockup_bytes and variant_config:
                mockup = Image.open(io.BytesIO(mockup_bytes)).convert("RGBA")
                result = build_frame(media_img, mockup, logo_img, variant_config)
            else:
                result = media_img.convert("RGB")
            out_path = str(OUTPUT_DIR / f"{output_filename}.png")
            result.save(out_path)
            download_name = "mockup.png"

        else:
            return jsonify({"error": "Unsupported file type"}), 400

    return jsonify({
        "download_url": url_for("download", filename=Path(out_path).name),
        "download_name": download_name,
    })


@app.route("/download/<filename>")
def download(filename):
    path = OUTPUT_DIR / secure_filename(filename)
    if not path.exists():
        return "File not found", 404
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
