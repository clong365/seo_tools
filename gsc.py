#!/usr/bin/env python3
"""GSC 收录/表现复查 — service account 只读（共享版）。"""
import re

SCOPES = [
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
DEFAULT_KEY = "~/.config/seo-tools/gsc-sa.json"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"


def normalize_site(s):
    s = (s or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s)
    return s.split("/", 1)[0]


def pick_site(sites, want):
    want = normalize_site(want)
    for s in sites:
        if normalize_site(s) == want:
            return s
    for s in sites:
        if want in s:
            return s
    return None


def parse_sitemap_locs(xml_text):
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text or "")


def is_sitemap_index(locs):
    return bool(locs) and all(loc.rstrip("/").endswith(".xml") for loc in locs)
