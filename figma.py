"""Figma API integration — fetches and exports component variants."""

import os
import requests

FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN")
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "WRPoyXiU5wyxxTOYt9WZsF")
BASE_URL = "https://api.figma.com/v1"

HEADERS = {"X-Figma-Token": FIGMA_TOKEN} if FIGMA_TOKEN else {}

# Component node IDs for each device + format combination.
# These map to the "Unfilled" variants in the Ad Library.
COMPONENT_MAP = {
    "web": {
        "node_id": "9473:33325",   # Newsfeed Web - Mobile3.0
        "label": "Web (Mobile)",
    },
    "ios": {
        "node_id": "9582:268805",  # Newsfeed iOS - Mobile3.0
        "label": "iOS",
    },
    "android": {
        "node_id": "10040:113946", # Newsfeed Android - Mobile3.0
        "label": "Android",
    },
    "desktop": {
        "node_id": "9518:198767",  # Newsfeed Formats - Desktop 3.0
        "label": "Desktop",
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
        "note": "Body text is baked into the image",
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


def get_component_export_url(node_id: str, scale: float = 2.0) -> str | None:
    """Export a Figma node as PNG and return the download URL."""
    if not FIGMA_TOKEN:
        return None

    node_id_encoded = node_id.replace(":", "-")
    url = f"{BASE_URL}/images/{FIGMA_FILE_KEY}"
    params = {
        "ids": node_id,
        "format": "png",
        "scale": scale,
    }
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    images = data.get("images", {})
    return images.get(node_id) or images.get(node_id_encoded)


def export_component_png(node_id: str, scale: float = 2.0) -> bytes | None:
    """Download a Figma component as PNG bytes."""
    url = get_component_export_url(node_id, scale)
    if not url:
        return None
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def get_available_devices() -> dict:
    return {k: v["label"] for k, v in COMPONENT_MAP.items()}


def get_available_formats() -> dict:
    return {k: v["label"] for k, v in FORMAT_SPECS.items()}


def get_format_spec(format_key: str) -> dict | None:
    return FORMAT_SPECS.get(format_key)


def get_device_node_id(device_key: str) -> str | None:
    device = COMPONENT_MAP.get(device_key)
    return device["node_id"] if device else None
