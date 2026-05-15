from __future__ import annotations

import html
import re
import shutil
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Bitwise brand palette (from bitwise-hq visual-system.md)
# ---------------------------------------------------------------------------
BRAND_PRIMARY = "#5B4FE8"
BRAND_INK = "#16142B"
BRAND_SLATE = "#6E6B88"
BRAND_MIST = "#E6E5F2"
BRAND_CLOUD = "#F5F4FF"

ADDONS = (
    "bwt_webhooks_core",
    "bwt_webhooks_inbound",
    "bwt_webhooks_outbound",
    "bwt_connector_webhooks_core",
)

BANNER_ADDONS = (
    "bwt_webhooks_core",
    "bwt_webhooks_inbound",
    "bwt_webhooks_outbound",
    "bwt_connector_webhooks_core",
    "bwt_connector_webhooks_inbound",
    "bwt_connector_webhooks_outbound",
)

COVER_ADDONS = BANNER_ADDONS

# Map addon → human display name
ADDON_NAMES = {
    "bwt_webhooks_core": "Webhooks Framework - Core Orchestration",
    "bwt_webhooks_inbound": "Webhooks Framework - Inbound Gateway",
    "bwt_webhooks_outbound": "Webhooks Framework - Outbound Delivery",
    "bwt_connector_webhooks_core": "Connector Webhooks - Glue Core",
    "bwt_connector_webhooks_inbound": "Connector Webhooks - Glue Inbound",
    "bwt_connector_webhooks_outbound": "Connector Webhooks - Glue Outbound",
}

# Map addon → tagline
ADDON_TAGLINES = {
    "bwt_webhooks_core": "Production-grade webhook orchestration for Odoo.",
    "bwt_webhooks_inbound": "Secure inbound endpoints with signatures, replay protection, and rule-based processing.",
    "bwt_webhooks_outbound": "Reliable outbound delivery with templated requests, retries, and diagnostics.",
    "bwt_connector_webhooks_core": "Shared base and mixins for connector backends that own webhook endpoints.",
    "bwt_connector_webhooks_inbound": "Mixin for connector backends to receive and process inbound webhooks.",
    "bwt_connector_webhooks_outbound": "Mixin for connector backends to send outbound webhooks reliably.",
}


# ---------------------------------------------------------------------------
# RST → plain-text helpers
# ---------------------------------------------------------------------------


def _strip_rst(text: str) -> str:
    """Remove RST inline markup and directives for plain-text use."""
    text = re.sub(r"\.\. [a-z_-]+::.*", "", text)  # directives
    text = re.sub(r"^\s+:\w.*", "", text, flags=re.MULTILINE)  # options
    text = re.sub(r"``([^`]+)``", r"<code>\1</code>", text)  # ``code``
    text = re.sub(r"`([^`]+)`_", r"\1", text)  # `link`_
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)  # **bold**
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)  # *italic*
    text = text.replace("\u2014", "-").replace("\u2013", "-")  # em/en dash -> hyphen
    text = text.replace("\u2192", "->")  # right arrow -> ASCII
    return text.strip()


def _parse_bullets(text: str) -> list[str]:
    """Extract bullet items from an RST bullet list block."""
    items = []
    for line in text.splitlines():
        m = re.match(r"^[-*]\s+(.*)", line.strip())
        if m:
            items.append(_strip_rst(m.group(1)))
    return items


def _parse_sections(rst: str) -> dict:
    """
    Extract structured content from an oca-gen-addon-readme README.rst.

    Returns a dict with keys:
      title, highlights (list), diagrams (list of (src, alt)),
      usage_steps (list), configure_steps (list), cta (str)
    """
    # Strip the generated comment block at the top
    rst = re.sub(r"^\.\. !!+.*?!!\n", "", rst, flags=re.MULTILINE | re.DOTALL)

    result: dict = {
        "title": "",
        "highlights": [],
        "diagrams": [],
        "usage_steps": [],
        "configure_steps": [],
        "cta": "",
    }

    # Title: first non-blank line before a line of = or #
    title_m = re.search(r"^(.+)\n[=#+*^]{3,}\n", rst, re.MULTILINE)
    if title_m:
        result["title"] = title_m.group(1).strip()

    # Highlights: bullet list after "Highlights"
    hl_m = re.search(r"\*\*Highlights[:\*]*\*\*\s*\n((?:[-*] .+\n?)+)", rst, re.MULTILINE)
    if hl_m:
        result["highlights"] = _parse_bullets(hl_m.group(1))

    # Diagrams: .. image:: directives (local path or raw.githubusercontent URL)
    # oca-gen-addon-readme rewrites local paths to full raw.githubusercontent URLs;
    # strip back to just `diagrams/filename.svg` (relative to static/description/)
    _raw_prefix = re.compile(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/[^/]+/static/description/")
    for img_m in re.finditer(
        r"\.\. image:: ([^\n]+)\n"
        r"(?:\s+:alt: ([^\n]+)\n)?",
        rst,
    ):
        src = img_m.group(1).strip()
        alt = (img_m.group(2) or "").strip()
        src = _raw_prefix.sub("", src)
        if src.startswith("diagrams/") or src.startswith("static/"):
            result["diagrams"].append((src, alt))

    # CTA: "Looking for turnkey…" — grab entire paragraph (until blank line)
    cta_m = re.search(r"(Looking for turnkey[^\n]*(?:\n[^\n]+)*)", rst)
    if cta_m:
        result["cta"] = " ".join(cta_m.group(1).split())

    # Split RST into named sections using [^\n]+ to avoid DOTALL crossing lines
    sections_map: dict[str, str] = {}
    for sec_m in re.finditer(
        r"^([^\n]+)\n([=\-~^+*#]{3,})\n(.*?)(?=^[^\n]+\n[=\-~^+*#]{3,}\n|\Z)",
        rst,
        re.MULTILINE | re.DOTALL,
    ):
        heading = sec_m.group(1).strip()
        body = sec_m.group(3)
        sections_map[heading] = body

    result["usage_steps"] = _extract_numbered(sections_map.get("Usage", ""))
    result["configure_steps"] = _extract_numbered(sections_map.get("Configuration", ""))

    return result


def _extract_numbered(text: str) -> list[str]:
    items = []
    for line in text.splitlines():
        m = re.match(r"^\d+\.\s+(.*)", line.strip())
        if m:
            items.append(_strip_rst(m.group(1)))
    return items


# ---------------------------------------------------------------------------
# Style preamble — single scoped <style> block, mobile-first, no Odoo grid
# ---------------------------------------------------------------------------

_STYLE_BLOCK = f"""<style>
.bwt-app {{
  font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: {BRAND_INK};
  line-height: 1.6;
  font-size: 15px;
  overflow-x: hidden;
}}
.bwt-app *, .bwt-app *::before, .bwt-app *::after {{ box-sizing: border-box; }}
.bwt-app img {{ max-width: 100%; height: auto; display: block; }}
.bwt-app a {{ color: {BRAND_PRIMARY}; }}
.bwt-app .bwt-section {{ padding: 40px 16px; }}
.bwt-app .bwt-wrap {{ max-width: 960px; margin: 0 auto; width: 100%; }}
.bwt-app .bwt-hero {{ background: {BRAND_CLOUD}; text-align: center; }}
.bwt-app .bwt-alt {{ background: {BRAND_CLOUD}; }}
.bwt-app .bwt-diagram {{ background: {BRAND_MIST}; text-align: center; overflow: hidden; }}
.bwt-app .bwt-diagram img {{ margin: 0 auto; border-radius: 8px; box-shadow: 0 2px 12px rgba(91,79,232,0.10); }}
.bwt-app .bwt-cta {{ background: {BRAND_PRIMARY}; text-align: center; }}
.bwt-app .bwt-cta p {{ color: #fff; font-size: 16px; margin: 0; }}
.bwt-app .bwt-guide {{ border-top: 1px solid {BRAND_MIST}; }}
.bwt-app .bwt-guide-title {{
  font-family: 'Space Grotesk', sans-serif;
  color: {BRAND_PRIMARY};
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 24px;
  padding-bottom: 12px;
  border-bottom: 2px solid {BRAND_MIST};
}}
.bwt-app h1, .bwt-app h2, .bwt-app h3, .bwt-app h4 {{
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 600;
  line-height: 1.3;
  margin: 0 0 16px;
}}
.bwt-app .bwt-name {{ color: {BRAND_PRIMARY}; font-size: 26px; font-weight: 700; margin-top: 20px; }}
.bwt-app .bwt-tagline {{ color: {BRAND_INK}; font-weight: 400; font-size: 18px; margin-top: 8px; }}
.bwt-app .bwt-section h2 {{ color: {BRAND_PRIMARY}; font-size: 22px; font-weight: 700; }}
.bwt-app .bwt-section h3 {{ color: {BRAND_INK}; font-size: 17px; margin-top: 24px; }}
.bwt-app .bwt-section h4 {{ color: {BRAND_SLATE}; font-size: 15px; margin-top: 20px; }}
.bwt-app p {{ margin: 0 0 12px; }}
.bwt-app ul, .bwt-app ol {{ padding-left: 24px; margin: 0 0 16px; }}
.bwt-app li {{ margin-bottom: 6px; }}
.bwt-app code {{
  background: {BRAND_MIST};
  color: {BRAND_INK};
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'IBM Plex Mono', Menlo, Consolas, monospace;
  word-break: break-word;
}}
.bwt-app pre {{
  background: {BRAND_INK};
  color: {BRAND_CLOUD};
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
  font-family: 'IBM Plex Mono', Menlo, Consolas, monospace;
  line-height: 1.5;
  margin: 0 0 16px;
  max-width: 100%;
}}
.bwt-app pre code {{ background: transparent; color: inherit; padding: 0; }}
.bwt-app .bwt-caption {{ color: {BRAND_SLATE}; font-size: 13px; font-style: italic; margin: 10px 0 0; }}
.bwt-app .bwt-inline-img {{ margin: 20px 0; text-align: center; }}
@media (max-width: 600px) {{
  .bwt-app {{ font-size: 14px; }}
  .bwt-app .bwt-section {{ padding: 28px 14px; }}
  .bwt-app .bwt-name {{ font-size: 22px; }}
  .bwt-app .bwt-tagline {{ font-size: 16px; }}
  .bwt-app .bwt-section h2 {{ font-size: 19px; }}
  .bwt-app .bwt-section h3 {{ font-size: 16px; }}
  .bwt-app pre {{ font-size: 12px; padding: 12px; }}
}}
</style>"""


# ---------------------------------------------------------------------------
# RST guide renderer
# ---------------------------------------------------------------------------


def _render_guide_rst_to_html(
    rst_text: str,
    guide_title: str,
    alt_background: bool,
    skip_image_srcs: set[str] | None = None,
) -> str:
    """Convert a guide RST file to a brand-styled HTML section.

    Handles the subset of RST used in the guide files:
    headings (= / - / ~), bullet lists, numbered lists, code blocks
    (paragraph ending with ::\n\n<indented block>), image directives,
    and regular paragraphs with inline ``code``, **bold**, and *italic*.
    """
    lines = rst_text.splitlines()
    html_parts: list[str] = []
    i = 0
    n = len(lines)

    _UNDERLINE_CHARS = "=-~^+*#"
    _HEADING_TAG = {"=": "h2", "-": "h3", "~": "h4"}

    while i < n:
        line = lines[i]

        # -- blank line -------------------------------------------------------
        if not line.strip():
            i += 1
            continue

        # -- heading (look-ahead at underline line) ----------------------------
        if i + 1 < n:
            nxt = lines[i + 1].strip()
            if nxt and len(set(nxt)) == 1 and nxt[0] in _UNDERLINE_CHARS and len(nxt) >= 3:
                tag = _HEADING_TAG.get(nxt[0], "h4")
                text = _strip_rst(line.strip())
                html_parts.append(f"      <{tag}>{text}</{tag}>")
                i += 2
                continue

        # -- image directive --------------------------------------------------
        if line.strip().startswith(".. image::"):
            src = line.strip()[len(".. image::"):].strip()
            src = re.sub(r"^\.\./static/description/", "", src)
            i += 1
            alt = ""
            while i < n and lines[i].startswith("   "):
                opt_m = re.match(r"\s+:alt:\s+(.*)", lines[i])
                if opt_m:
                    alt = html.escape(opt_m.group(1).strip())
                i += 1
            if skip_image_srcs and src in skip_image_srcs:
                continue
            html_parts.append(
                f'      <div class="bwt-inline-img"><img src="{html.escape(src)}" alt="{alt}"/></div>'
            )
            continue

        # -- other directives (skip block) ------------------------------------
        if line.strip().startswith(".. "):
            i += 1
            while i < n and (lines[i].startswith("   ") or not lines[i].strip()):
                i += 1
            continue

        # -- bullet list ------------------------------------------------------
        if re.match(r"^\s*[-*]\s", line):
            items: list[str] = []
            while i < n:
                stripped = lines[i].strip()
                m = re.match(r"^[-*]\s+(.*)", stripped)
                if m:
                    items.append(m.group(1))
                    i += 1
                    while i < n and lines[i].startswith("  ") and not re.match(r"^\s*[-*]\s", lines[i]):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                elif not stripped:
                    break
                else:
                    break
            lis = "\n".join(f"        <li>{_strip_rst(item)}</li>" for item in items)
            html_parts.append(f"      <ul>\n{lis}\n      </ul>")
            continue

        # -- numbered list ----------------------------------------------------
        if re.match(r"^\s*\d+\.\s", line):
            items = []
            while i < n:
                stripped = lines[i].strip()
                m = re.match(r"^\d+\.\s+(.*)", stripped)
                if m:
                    items.append(m.group(1))
                    i += 1
                    while i < n and lines[i].startswith("   ") and not re.match(r"^\s*\d+\.\s", lines[i]):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                elif not stripped:
                    break
                else:
                    break
            lis = "\n".join(f"        <li>{_strip_rst(item)}</li>" for item in items)
            html_parts.append(f"      <ol>\n{lis}\n      </ol>")
            continue

        # -- paragraph (may end with :: intro for a code block) ---------------
        para_lines: list[str] = []
        while i < n and lines[i].strip() and not re.match(r"^\s*[-*]\s", lines[i]) and not re.match(r"^\s*\d+\.\s", lines[i]):
            para_lines.append(lines[i].rstrip())
            i += 1

        if not para_lines:
            i += 1
            continue

        full_text = " ".join(line.strip() for line in para_lines)

        if full_text.rstrip().endswith("::"):
            intro = full_text.rstrip()[:-2].strip()
            while i < n and not lines[i].strip():
                i += 1
            code_lines: list[str] = []
            while i < n:
                if not lines[i].strip():
                    code_lines.append("")
                    i += 1
                elif lines[i][0:1] in (" ", "\t"):
                    code_lines.append(lines[i].rstrip())
                    i += 1
                else:
                    break
            while code_lines and not code_lines[-1]:
                code_lines.pop()
            indented = [line for line in code_lines if line.strip()]
            if indented:
                min_ind = min(len(line) - len(line.lstrip()) for line in indented)
                code_lines = [line[min_ind:] if line.strip() else "" for line in code_lines]
            code_content = (
                html.escape("\n".join(code_lines))
                .replace("\u2014", "-")
                .replace("\u2013", "-")
                .replace("\u2192", "->")
            )
            if intro:
                html_parts.append(f"      <p>{_strip_rst(intro)}</p>")
            html_parts.append(f"      <pre>{code_content}</pre>")
        else:
            html_parts.append(f"      <p>{_strip_rst(full_text)}</p>")

    content = "\n".join(html_parts)
    section_classes = "bwt-section bwt-guide" + (" bwt-alt" if alt_background else "")
    return f"""
<section class="{section_classes}">
  <div class="bwt-wrap">
    <h2 class="bwt-guide-title">{guide_title}</h2>
{content}
  </div>
</section>"""


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _render_banner(
    cover_path: Path,
    output_path: Path,
    name: str,
    tagline: str,
    fonts_dir: Path,
) -> None:
    """Composite name + tagline text over the cover image and write banner.png."""
    BW, BH = 528, 264  # Odoo app-store banner dimensions

    # Scale cover to full banner width (covers are 3:1, banners are 2:1).
    # Top-align so no letterbox band appears at the top.
    src = Image.open(cover_path).convert("RGBA")
    sw, sh = src.size
    scale = BW / sw
    rw, rh = BW, max(1, int(sh * scale))
    src = src.resize((rw, rh), Image.LANCZOS)

    ink_r, ink_g, ink_b = _hex_to_rgb(BRAND_INK)

    paste_y = (BH - rh) // 2
    bottom_pad = BH - (paste_y + rh)
    safe_slice_h = max(1, min(20, rh // 8))

    # Fill only the padding with safe background-only slices from the cover so
    # the gradient matches without repeating the zigzag wave shapes.
    img = Image.new("RGBA", (BW, BH), (0, 0, 0, 0))
    if paste_y > 0:
        top_slice = src.crop((0, 0, BW, safe_slice_h)).resize((BW, paste_y), Image.LANCZOS)
        img.paste(top_slice, (0, 0))
    if bottom_pad > 0:
        bottom_slice = src.crop((0, rh - safe_slice_h, BW, rh)).resize((BW, bottom_pad), Image.LANCZOS)
        img.paste(bottom_slice, (0, paste_y + rh))

    # Paste the centred artwork directly so the cover itself stays crisp.
    img.paste(src, (0, paste_y))

    # Gradient scrim starts inside the lower artwork region and ramps to
    # near-opaque at the canvas bottom for text readability.
    overlay = Image.new("RGBA", (BW, BH), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    grad_start = paste_y + int(rh * 0.72)
    for gy in range(grad_start, BH):
        alpha = int(220 * (gy - grad_start) / (BH - grad_start))
        draw_ov.line([(0, gy), (BW - 1, gy)], fill=(ink_r, ink_g, ink_b, alpha))
    img = Image.alpha_composite(img, overlay)

    # Fonts — sized for 528×264
    font_path = fonts_dir / "space-grotesk" / "SpaceGrotesk[wght].ttf"
    try:
        name_font = ImageFont.truetype(str(font_path), 20)
        try:
            name_font.set_variation_by_axes([700])
        except (OSError, AttributeError):
            pass
        tagline_font = ImageFont.truetype(str(font_path), 12)
        try:
            tagline_font.set_variation_by_axes([400])
        except (OSError, AttributeError):
            pass
    except OSError:
        name_font = ImageFont.load_default()
        tagline_font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    cx = BW // 2

    name_lines = textwrap.wrap(name, width=40) or [name]
    tagline_lines = textwrap.wrap(tagline, width=70) or ([tagline] if tagline else [])

    def _line_h(font: ImageFont.FreeTypeFont, extra: int = 3) -> int:
        bb = draw.textbbox((0, 0), "Ay", font=font, anchor="lt")
        return bb[3] - bb[1] + extra

    name_lh = _line_h(name_font, 4)
    tag_lh = _line_h(tagline_font, 3)
    gap = 5
    total_h = len(name_lines) * name_lh + (gap + len(tagline_lines) * tag_lh if tagline_lines else 0)

    # Centre text block in the bottom quarter of the canvas
    text_zone_top = BH - 72
    text_zone_bottom = BH - 10
    ty = text_zone_top + max(0, (text_zone_bottom - text_zone_top - total_h) // 2)

    for line in name_lines:
        draw.text((cx, ty), line, font=name_font, fill=(255, 255, 255, 255), anchor="mt")
        ty += name_lh

    if tagline_lines:
        ty += gap
        mist_r, mist_g, mist_b = _hex_to_rgb(BRAND_MIST)
        for line in tagline_lines:
            draw.text((cx, ty), line, font=tagline_font, fill=(mist_r, mist_g, mist_b, 230), anchor="mt")
            ty += tag_lh

    img.convert("RGB").save(str(output_path), "PNG", optimize=True)


def _copy_banners(
    repo_root: Path,
    addon_names: dict[str, str],
    addon_taglines: dict[str, str],
) -> None:
    """Generate banner.png for each addon by overlaying text on the cover image."""
    cover_root = repo_root / "assets" / "covers"
    fonts_dir = repo_root / "assets" / "fonts"
    for addon in BANNER_ADDONS:
        source = cover_root / f"{addon}.png"
        if not source.exists():
            raise FileNotFoundError(f"Missing cover asset: {source}")
        name = addon_names.get(addon, addon.replace("_", " ").title())
        tagline = addon_taglines.get(addon, "")
        target = repo_root / addon / "static" / "description" / "banner.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        _render_banner(source, target, name, tagline, fonts_dir)


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def _li(items: list[str]) -> str:
    return "\n".join(f"        <li>{i}</li>" for i in items)


def render_description(readme_path: Path, output_path: Path, addon: str) -> None:
    rst = readme_path.read_text(encoding="utf-8")
    sections = _parse_sections(rst)

    name = ADDON_NAMES.get(addon, sections["title"] or addon)
    tagline = ADDON_TAGLINES.get(addon, "")
    highlights = sections["highlights"]
    diagrams = sections["diagrams"]
    usage_steps = sections["usage_steps"]
    configure_steps = sections["configure_steps"]
    cta = sections["cta"]
    diagram_srcs = {src for src, _ in diagrams}

    parts: list[str] = []
    parts.append('<div class="bwt-app">')
    parts.append(_STYLE_BLOCK)

    # --- Hero ---
    parts.append(f"""
<section class="bwt-section bwt-hero">
  <div class="bwt-wrap">
    <h1 class="bwt-name">{html.escape(name)}</h1>
    <p class="bwt-tagline">{html.escape(tagline)}</p>
  </div>
</section>""")

    # --- Highlights ---
    if highlights:
        parts.append(f"""
<section class="bwt-section">
  <div class="bwt-wrap">
    <h2>Key Features</h2>
    <ul>
{_li(highlights)}
    </ul>
  </div>
</section>""")

    # --- Diagrams ---
    for src, alt in diagrams:
        parts.append(f"""
<section class="bwt-section bwt-diagram">
  <div class="bwt-wrap">
    <img src="{html.escape(src)}" alt="{html.escape(alt)}"/>
  </div>
</section>""")

    # --- Configure ---
    if configure_steps:
        parts.append(f"""
<section class="bwt-section">
  <div class="bwt-wrap">
    <h2>Configuration</h2>
    <ol>
{_li(configure_steps)}
    </ol>
  </div>
</section>""")

    # --- Usage ---
    if usage_steps:
        parts.append(f"""
<section class="bwt-section bwt-alt">
  <div class="bwt-wrap">
    <h2>Usage</h2>
    <ol>
{_li(usage_steps)}
    </ol>
  </div>
</section>""")

    # --- CTA ---
    if cta:
        parts.append(f"""
<section class="bwt-section bwt-cta">
  <div class="bwt-wrap">
    <p>{html.escape(cta)}</p>
  </div>
</section>""")

    # --- Operator Guide ---
    addon_root = readme_path.parent
    op_guide_path = addon_root / "readme" / "OPERATOR_GUIDE.rst"
    if op_guide_path.exists():
        op_text = op_guide_path.read_text(encoding="utf-8")
        parts.append(
            _render_guide_rst_to_html(
                op_text,
                "Operator Guide",
                alt_background=True,
                skip_image_srcs=diagram_srcs,
            )
        )

    # --- Developer Guide ---
    dev_guide_path = addon_root / "readme" / "DEVELOPER_GUIDE.rst"
    if dev_guide_path.exists():
        dev_text = dev_guide_path.read_text(encoding="utf-8")
        parts.append(
            _render_guide_rst_to_html(
                dev_text,
                "Developer Guide",
                alt_background=False,
                skip_image_srcs=diagram_srcs,
            )
        )

    parts.append("</div>")
    html_text = "\n".join(parts) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        with open(output_path, encoding="utf-8", newline="") as fh:
            existing = fh.read()
    else:
        existing = None
    if existing != html_text:
        with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html_text)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    _copy_banners(repo_root, ADDON_NAMES, ADDON_TAGLINES)

    for addon in ADDONS:
        addon_root = repo_root / addon
        readme_path = addon_root / "README.rst"
        output_path = addon_root / "static" / "description" / "index.html"

        if not readme_path.exists():
            raise FileNotFoundError(f"Missing README.rst for {addon}")

        render_description(readme_path, output_path, addon)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
