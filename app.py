# ============================
# File: app.py
# ============================
from flask import Flask, request, jsonify
from pathlib import Path
import tempfile
import os

from cv import process_file

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

@app.route("/")
def home():
    return """
    <h2>Upload CV (PDF/TXT/Image)</h2>
    <form method="POST" enctype="multipart/form-data" action="/upload">
        <input type="file" name="cv" accept=".pdf,.txt,.png,.jpg,.jpeg" required>
        <br><br>
        <label>Phone Region: <input name="phone_region" placeholder="IN"></label>
        <br><br>
        <button type="submit">Upload & Extract</button>
    </form>
    """

@app.route("/upload", methods=["POST"])
def upload():
    if "cv" not in request.files:
        return "No file uploaded", 400

    file = request.files["cv"]
    phone_region = request.form.get("phone_region")

    suffix = Path(file.filename).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(file.read())
    tmp.close()
    tmp_path = Path(tmp.name)

    out_dir = Path.cwd() / "uploads_output"
    out_dir.mkdir(exist_ok=True)

    try:
        result = process_file(tmp_path, phone_region, out_dir)
        return jsonify(result)
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass

if __name__ == "__main__":
    app.run(port=5000, host="0.0.0.0", debug=True)
