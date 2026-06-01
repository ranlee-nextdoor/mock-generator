"""Figma API integration — fetches and exports component variants."""

import os
import requests

FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN")
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "WRPoyXiU5wyxxTOYt9WZsF")
BASE_URL = "https://api.figma.com/v1"

HEADERS = {"X-Figma-Token": FIGMA_TOKEN} if FIGMA_TOKEN else {}

# Maps format_key → the Figma component "Format" variant name
FORMAT_TO_FIGMA_VARIANT = {
    "image_16_9":   "image",
    "image_1_1":    "image",
    "video_16_9":   "image",
    "video_1_1":    "image",
    "video_9_16":   "image",
    "lead_gen":     "lead_gen",
    "for_sale_free":"image",
    "carousel":     "carousel",
    "spotlight":    "spotlight",
    "right_hand_rail": "image",
}

# Specific "Unfilled" variant node IDs per device per format variant.
# Regions are at 1x (Figma canvas units); compositing scales to match export size.
COMPONENT_MAP = {
    "web": {
        "label": "Web (Mobile)",
        "variants": {
            "image":    {"node_id": "9473:33326", "component": {"width": 365, "height": 589}, "media_region": {"x": 0,  "y": 172, "width": 365, "height": 365}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "carousel": {"node_id": "9473:33680", "component": {"width": 375, "height": 506}, "media_region": {"x": 16, "y": 172, "width": 266, "height": 266}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "spotlight":{"node_id": "9473:33637", "component": {"width": 365, "height": 365}, "media_region": {"x": 0,  "y": 0,   "width": 365, "height": 365}, "logo_region": {"x": 310, "y": 308, "width": 40, "height": 40}},
            "lead_gen": {"node_id": "9509:144999","component": {"width": 365, "height": 589}, "media_region": {"x": 0,  "y": 172, "width": 365, "height": 365}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
        },
    },
    "ios": {
        "label": "iOS",
        "variants": {
            "image":    {"node_id": "9582:268806", "component": {"width": 393, "height": 617}, "media_region": {"x": 0, "y": 172, "width": 393, "height": 393}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "carousel": {"node_id": "9582:268928", "component": {"width": 393, "height": 506}, "media_region": {"x": 16, "y": 172, "width": 266, "height": 266}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "spotlight":{"node_id": "9582:268866", "component": {"width": 393, "height": 393}, "media_region": {"x": 0, "y": 0, "width": 393, "height": 393}, "logo_region": {"x": 335, "y": 335, "width": 40, "height": 40}},
            "lead_gen": {"node_id": "9582:269080", "component": {"width": 393, "height": 617}, "media_region": {"x": 0, "y": 172, "width": 393, "height": 393}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
        },
    },
    "android": {
        "label": "Android",
        "variants": {
            "image":    {"node_id": "10040:113947", "component": {"width": 393, "height": 617}, "media_region": {"x": 0, "y": 172, "width": 393, "height": 393}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "carousel": {"node_id": "10040:113983", "component": {"width": 393, "height": 506}, "media_region": {"x": 16, "y": 172, "width": 266, "height": 266}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "spotlight":{"node_id": "10040:113971", "component": {"width": 393, "height": 393}, "media_region": {"x": 0, "y": 0, "width": 393, "height": 393}, "logo_region": {"x": 335, "y": 335, "width": 40, "height": 40}},
            "lead_gen": {"node_id": "10040:114135", "component": {"width": 393, "height": 617}, "media_region": {"x": 0, "y": 172, "width": 393, "height": 393}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
        },
    },
    "desktop": {
        "label": "Desktop",
        "variants": {
            "image":    {"node_id": "9518:198768", "component": {"width": 580, "height": 804}, "media_region": {"x": 0, "y": 172, "width": 580, "height": 580}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "carousel": {"node_id": "9518:198890", "component": {"width": 580, "height": 700}, "media_region": {"x": 16, "y": 172, "width": 400, "height": 400}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
            "spotlight":{"node_id": "9518:198828", "component": {"width": 580, "height": 580}, "media_region": {"x": 0, "y": 0, "width": 580, "height": 580}, "logo_region": {"x": 500, "y": 498, "width": 40, "height": 40}},
            "lead_gen": {"node_id": "9556:240772", "component": {"width": 580, "height": 804}, "media_region": {"x": 0, "y": 172, "width": 580, "height": 580}, "logo_region": {"x": 16, "y": 16, "width": 40, "height": 40}},
        },
    },
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


def get_variant_config(device_key: str, format_key: str) -> dict | None:
    """Return the node ID + region config for the right device+format variant."""
    device = COMPONENT_MAP.get(device_key)
    if not device:
        return None
    figma_variant = FORMAT_TO_FIGMA_VARIANT.get(format_key, "image")
    return device["variants"].get(figma_variant)


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
    return {k: v["label"] for k, v in FORMAT_SPECS.items()}


def get_format_spec(format_key: str) -> dict | None:
    return FORMAT_SPECS.get(format_key)
