import os
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from main import composite_frames, load_templates, save_gif, video_to_frames

app = Flask(__name__, template_folder="templates_html")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB upload limit

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "webm", "mkv"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    templates = load_templates()
    return render_template("index.html", templates=templates)


@app.route("/generate", methods=["POST"])
def generate():
    if "video" not in request.files:
        return jsonify({"error": "No video file uploaded"}), 400

    file = request.files["video"]
    template_name = request.form.get("template")
    fps = int(request.form.get("fps", 15))
    duration = float(request.form.get("duration", 5))

    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    templates = load_templates()
    if template_name not in templates:
        return jsonify({"error": f"Template '{template_name}' not found"}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, secure_filename(file.filename))
        file.save(video_path)

        try:
            frames = video_to_frames(video_path, fps, duration, tmpdir)
            composited = composite_frames(frames, templates[template_name])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    output_filename = f"{uuid.uuid4().hex}.gif"
    output_path = OUTPUT_DIR / output_filename
    save_gif(composited, str(output_path), fps)

    return jsonify({"download_url": url_for("download", filename=output_filename)})


@app.route("/download/<filename>")
def download(filename):
    path = OUTPUT_DIR / secure_filename(filename)
    if not path.exists():
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name="mockup.gif")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
