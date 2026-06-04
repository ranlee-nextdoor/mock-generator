"""Figma API integration — fetches and exports component variants."""

import os
import requests

FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN")
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "racGTQJtcB6f7fZlH1NyVL")
BASE_URL = "https://api.figma.com/v1"

HEADERS = {"X-Figma-Token": FIGMA_TOKEN} if FIGMA_TOKEN else {}

# Format frames from the new Mock Maker 2026 file — transparent media regions.
# All formats are device-agnostic (device context handled separately).
# logo_region is None — logo placeholder is transparent, composited by client.
_LOGO = {"x": 16, "y": 16, "width": 40, "height": 40}

FORMAT_FRAMES = {
    "image_1_1":    {"node_id": "10001:9797", "component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "image_16_9":   {"node_id": "10003:2873", "component": {"width": 365, "height": 419}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 195}, "logo_region": _LOGO},
    "video_1_1":    {"node_id": "10001:9797", "component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "video_16_9":   {"node_id": "10003:2873", "component": {"width": 365, "height": 419}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 195}, "logo_region": _LOGO},
    "video_9_16":   {"node_id": "10001:9797", "component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "spotlight":    {"node_id": "10001:9828", "component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "carousel":     {"node_id": "10001:9836", "component": {"width": 375, "height": 506}, "media_region": {"x": 0, "y": 172, "width": 375, "height": 334}, "logo_region": _LOGO},
    "lead_gen":     {"node_id": "10001:10120","component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "for_sale_free":{"node_id": "10001:9797", "component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
    "right_hand_rail":{"node_id":"10001:9797","component": {"width": 365, "height": 589}, "media_region": {"x": 0, "y": 172, "width": 365, "height": 365}, "logo_region": _LOGO},
}

# Device labels for the UI dropdown
COMPONENT_MAP = {
    "web":     {"label": "Web (mobile)"},
    "ios":     {"label": "iOS"},
    "android": {"label": "Android"},
    "desktop": {"label": "Desktop"},
}

# Format specs derived from the ad specs sheet
FORMAT_SPECS = {
    "image_16_9": {
        "label": "Image (16:9)",
        "media_type": "image",
        "aspect_ratio": "16:9",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "image_1_1": {
        "label": "Image (1:1)",
        "media_type": "image",
        "aspect_ratio": "1:1",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "video_16_9": {
        "label": "Video (16:9)",
        "media_type": "video",
        "aspect_ratio": "16:9",
        "max_file_mb": 500,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "video_1_1": {
        "label": "Video (1:1)",
        "media_type": "video",
        "aspect_ratio": "1:1",
        "max_file_mb": 500,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "video_9_16": {
        "label": "Vertical Video (9:16)",
        "media_type": "video",
        "aspect_ratio": "9:16",
        "max_file_mb": 500,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
        "note": "Mobile only",
    },
    "lead_gen": {
        "label": "Lead Gen",
        "media_type": "image_or_video",
        "aspect_ratio": "1:1 or 16:9",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 45,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "for_sale_free": {
        "label": "For Sale & Free",
        "media_type": "image",
        "aspect_ratio": "1:1",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": None,
        "cta_limit": None,
        "has_body": False,
        "has_cta": False,
        "has_logo": False,
    },
    "carousel": {
        "label": "Carousel",
        "media_type": "image_or_video",
        "aspect_ratio": "1:1",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": 1700,
        "cta_limit": 30,
        "has_body": True,
        "has_cta": True,
        "has_logo": True,
    },
    "spotlight": {
        "label": "Spotlight",
        "media_type": "image",
        "aspect_ratio": "1:1",
        "max_file_mb": 150,
        "headline_limit": None,
        "body_limit": 30,
        "cta_limit": None,
        "has_body": True,
        "has_cta": False,
        "has_logo": True,
        "note": "Body text baked into image",
    },
    "right_hand_rail": {
        "label": "Right Hand Rail",
        "media_type": "image",
        "aspect_ratio": "1:1",
        "max_file_mb": 150,
        "headline_limit": 70,
        "body_limit": None,
        "cta_limit": 45,
        "has_body": False,
        "has_cta": True,
        "has_logo": True,
        "note": "Desktop only",
    },
}


FRAME_CACHE = {
    "image_1_1":       "frame_newsfeed_1x1.png",
    "video_1_1":       "frame_newsfeed_1x1.png",
    "video_9_16":      "frame_newsfeed_1x1.png",
    "image_16_9":      "frame_newsfeed_16x9.png",
    "video_16_9":      "frame_newsfeed_16x9.png",
    "spotlight":       "frame_personalized_1x1.png",
    "carousel":        "frame_carousel.png",
    "lead_gen":        "frame_lead_gen.png",
    "for_sale_free":   "frame_newsfeed_1x1.png",
    "right_hand_rail": "frame_newsfeed_1x1.png",
}


def get_variant_config(device_key: str, format_key: str) -> dict | None:
    """Return the node ID + region config for the given format (device-agnostic)."""
    return FORMAT_FRAMES.get(format_key)


def get_component_export_url(node_id: str, scale: float = 2.0) -> str | None:
    """Return the CDN URL for a Figma node PNG export (without downloading it)."""
    if not FIGMA_TOKEN:
        return None
    url = f"{BASE_URL}/images/{FIGMA_FILE_KEY}"
    params = {"ids": node_id, "format": "png", "scale": scale}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    images = resp.json().get("images", {})
    return images.get(node_id) or images.get(node_id.replace(":", "-"))


def export_component_png(node_id: str, scale: float = 2.0) -> bytes | None:
    """Export a Figma node as PNG and return raw bytes."""
    if not FIGMA_TOKEN:
        return None
    url = f"{BASE_URL}/images/{FIGMA_FILE_KEY}"
    params = {"ids": node_id, "format": "png", "scale": scale}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    images = resp.json().get("images", {})
    img_url = images.get(node_id) or images.get(node_id.replace(":", "-"))
    if not img_url:
        return None
    resp2 = requests.get(img_url, timeout=60)
    resp2.raise_for_status()
    return resp2.content


def get_available_devices() -> dict:
    return {k: v["label"] for k, v in COMPONENT_MAP.items()}

def get_available_formats() -> dict:
    return {k: FORMAT_SPECS[k]["label"] for k in FORMAT_FRAMES if k in FORMAT_SPECS}


def get_available_formats() -> dict:
    return {k: v["label"] for k, v in FORMAT_SPECS.items()}


def get_format_spec(format_key: str) -> dict | None:
    return FORMAT_SPECS.get(format_key)
