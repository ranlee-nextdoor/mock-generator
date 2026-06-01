import io
import os
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, url_for
from PIL import Image
from werkzeug.utils import secure_filename

import figma as figma_api
from main import composite_frames, save_gif, video_to_frames

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


@app.route("/")
def index():
    devices = figma_api.get_available_devices()
    formats = figma_api.get_available_formats()
    format_specs = figma_api.FORMAT_SPECS
    return render_template("index.html", devices=devices, formats=formats, format_specs=format_specs)


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
    fps = int(request.form.get("fps", 15))
    duration = float(request.form.get("duration", 5))

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
        errors.append(f"Headline exceeds {spec['headline_limit']} character limit")
    if spec["body_limit"] and body and len(body) > spec["body_limit"]:
        errors.append(f"Body exceeds {spec['body_limit']} character limit")
    if spec["cta_limit"] and cta and len(cta) > spec["cta_limit"]:
        errors.append(f"CTA exceeds {spec['cta_limit']} character limit")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    # Export the Figma device frame as the base mockup
    node_id = figma_api.get_device_node_id(device_key)
    mockup_bytes = figma_api.export_component_png(node_id) if node_id else None

    output_filename = f"{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory() as tmpdir:
        media_path = os.path.join(tmpdir, secure_filename(media_file.filename))
        media_file.save(media_path)

        logo_img = None
        if logo_file and logo_file.filename:
            logo_img = Image.open(logo_file).convert("RGBA")

        if is_video(media_file.filename):
            # Video → GIF output
            frames = video_to_frames(media_path, fps, duration, tmpdir)

            if mockup_bytes:
                composited = composite_with_mockup(frames, mockup_bytes, logo_img, headline, body, cta)
            else:
                composited = [f.convert("RGB") for f in frames]

            out_path = str(OUTPUT_DIR / f"{output_filename}.gif")
            save_gif(composited, out_path, fps)
            download_name = "mockup.gif"

        elif is_image(media_file.filename):
            # Static image → PNG output
            media_img = Image.open(media_path).convert("RGBA")

            if mockup_bytes:
                result = composite_static(media_img, mockup_bytes, logo_img, headline, body, cta)
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


def composite_with_mockup(frames, mockup_bytes, logo_img, headline, body, cta):
    """Composite video frames onto the Figma mockup export."""
    mockup = Image.open(io.BytesIO(mockup_bytes)).convert("RGBA")
    results = []
    for frame in frames:
        base = mockup.copy()
        # Scale media to fill the mockup — centre crop
        media = frame.convert("RGBA").resize(mockup.size, Image.LANCZOS)
        # Place media behind the mockup frame
        combined = Image.new("RGBA", mockup.size)
        combined.paste(media, (0, 0))
        combined.paste(base, (0, 0), base)
        if logo_img:
            combined = paste_logo(combined, logo_img)
        results.append(combined.convert("RGB"))
    return results


def composite_static(media_img, mockup_bytes, logo_img, headline, body, cta):
    """Composite a static image onto the Figma mockup export."""
    mockup = Image.open(io.BytesIO(mockup_bytes)).convert("RGBA")
    media = media_img.resize(mockup.size, Image.LANCZOS).convert("RGBA")
    combined = Image.new("RGBA", mockup.size)
    combined.paste(media, (0, 0))
    combined.paste(mockup, (0, 0), mockup)
    if logo_img:
        combined = paste_logo(combined, logo_img)
    return combined.convert("RGB")


def paste_logo(base_img, logo_img, size=(100, 100), margin=20):
    """Paste logo in the bottom-left corner."""
    logo = logo_img.resize(size, Image.LANCZOS).convert("RGBA")
    x = margin
    y = base_img.height - size[1] - margin
    base_img.paste(logo, (x, y), logo)
    return base_img


@app.route("/download/<filename>")
def download(filename):
    path = OUTPUT_DIR / secure_filename(filename)
    if not path.exists():
        return "File not found", 404
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
