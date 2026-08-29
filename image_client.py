import websocket
import uuid
import json
import urllib.request
import urllib.error
import requests
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
server_address = "127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())
WORKFLOW_PATH = os.path.join(BASE_DIR, "rt_therapy_workflow.json")
IMG_BASE = os.path.join(BASE_DIR, "static", "img")
GENERATION_TIMEOUT = 180


def _ensure_dir(tab_id):
    path = os.path.join(IMG_BASE, tab_id)
    os.makedirs(path, exist_ok=True)
    return path


def _nostalgic_prefix():
    return (
        "oil painting style, warm nostalgic light, soft focus, "
        "photorealistic painterly "
        "highly detailed, cinematic composition — "
    )


def comfyui_available():
    try:
        urllib.request.urlopen(f"http://{server_address}/system_stats", timeout=3)
        return True
    except Exception:
        return False


def queue_prompt(prompt):
    payload = {"prompt": prompt, "client_id": CLIENT_ID}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server_address}/prompt"
    req = urllib.request.Request(url, data=data)
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def generate_placeholder(tab_id, prompt, version=1):
    """Warm placeholder scene card when ComfyUI is unavailable or fails."""
    save_dir = _ensure_dir(tab_id)
    filename = f"vt-{uuid.uuid4().hex[:8]}_v{version}_placeholder.png"
    save_path = os.path.join(save_dir, filename)

    width, height = 768, 512
    img = Image.new("RGB", (width, height), "#3d2e18")
    draw = ImageDraw.Draw(img)

    for y in range(height):
        shade = int(61 + (y / height) * 40)
        draw.line([(0, y), (width, y)], fill=(shade, shade - 10, shade - 25))

    margin = 48
    wrapped = textwrap.fill(prompt.strip() or "A cherished memory", width=42)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
        small = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
        small = font

    draw.rounded_rectangle(
        [margin, margin, width - margin, height - margin],
        radius=18,
        fill=(253, 248, 240),
        outline=(212, 168, 67),
        width=2,
    )
    draw.text((margin + 28, margin + 24), "Memory Scene", fill="#8a6a30", font=small)
    draw.multiline_text(
        (margin + 28, margin + 56),
        wrapped,
        fill="#2c2010",
        font=font,
        spacing=8,
    )
    img.save(save_path, "PNG")
    return filename


def generate_image(tab_id, prompt, version=1):
    """
    Generate an image via ComfyUI. Falls back to a placeholder card on failure.
    Always returns a filename when prompt is non-empty.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return None

    if not comfyui_available():
        print("[image_client] ComfyUI not reachable — using placeholder")
        return generate_placeholder(tab_id, prompt, version)

    full_prompt = _nostalgic_prefix() + prompt
    ws = None
    try:
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        payload["11"]["inputs"]["text"] = full_prompt

        ws = websocket.WebSocket()
        ws.settimeout(GENERATION_TIMEOUT)
        ws.connect(f"ws://{server_address}/ws?clientId={CLIENT_ID}")
        resp = queue_prompt(payload)
        prompt_id = resp["prompt_id"]

        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message["type"] == "executing":
                    data = message["data"]
                    if data["node"] is None and data["prompt_id"] == prompt_id:
                        break

        history_url = f"http://{server_address}/history/{prompt_id}"
        history_response = requests.get(history_url, timeout=15).json()
        outputs = history_response[prompt_id]["outputs"]

        for node_id in outputs:
            if "images" in outputs[node_id]:
                for img_info in outputs[node_id]["images"]:
                    src_name = img_info["filename"]
                    subfolder = img_info["subfolder"]
                    folder_type = img_info["type"]

                    view_url = (
                        f"http://{server_address}/view"
                        f"?filename={src_name}&subfolder={subfolder}&type={folder_type}"
                    )
                    out_name = f"vt-{uuid.uuid4().hex[:8]}_v{version}.png"
                    img_data = requests.get(view_url, timeout=30).content

                    save_dir = _ensure_dir(tab_id)
                    save_path = os.path.join(save_dir, out_name)
                    with open(save_path, "wb") as f:
                        f.write(img_data)
                    return out_name

    except Exception as e:
        print(f"[image_client] Generation failed: {e}")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    return generate_placeholder(tab_id, prompt, version)
