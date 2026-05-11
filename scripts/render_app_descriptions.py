from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

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
    "bwt_connector_webhooks_core": "Connector Webhooks - Core Integration Layer",
}

# Map addon → tagline
ADDON_TAGLINES = {
    "bwt_webhooks_core": "Production-grade webhook orchestration for Odoo.",
    "bwt_webhooks_inbound": "Secure inbound endpoints with signatures, replay protection, and rule-based processing.",
    "bwt_webhooks_outbound": "Reliable outbound delivery with templated requests, retries, and diagnostics.",
    "bwt_connector_webhooks_core": "Shared base and mixins for connector backends that own webhook endpoints.",
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
# RST guide renderer
# ---------------------------------------------------------------------------


def _render_guide_rst_to_html(
    rst_text: str,
    guide_title: str,
    bg_color: str,
    skip_image_srcs: set[str] | None = None,
) -> str:
    """Convert a guide RST file to a brand-styled HTML section.

    Handles the subset of RST used in the webhook guide files:
    headings (= / - / ~), bullet lists, numbered lists, code blocks
    (paragraph ending with ::\n\n<indented block>), image directives
    (skipped — diagrams appear in the main description above), and
    regular paragraphs with inline ``code``, **bold**, and *italic*.
    """
    lines = rst_text.splitlines()
    html_parts: list[str] = []
    i = 0
    n = len(lines)

    _UNDERLINE_CHARS = "=-~^+*#"
    _HEADING_STYLE: dict[str, tuple[str, str, str]] = {
        "=": ("h2", BRAND_PRIMARY, "20px"),
        "-": ("h3", BRAND_INK, "17px"),
        "~": ("h4", BRAND_SLATE, "15px"),
    }

    def _p(text: str) -> str:
        return f"      <p style=\"color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7; margin:0 0 12px;\">{_strip_rst(text)}</p>"

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
                char = nxt[0]
                tag, color, size = _HEADING_STYLE.get(char, ("h4", BRAND_SLATE, "15px"))
                text = _strip_rst(line.strip())
                html_parts.append(f"      <{tag} style=\"color:{color}; font-family:'Space Grotesk',sans-serif; font-size:{size}; font-weight:600; margin:28px 0 10px;\">{text}</{tag}>")
                i += 2
                continue

        # -- image directive: render as <img>, adjusting addon-relative path ----
        if line.strip().startswith(".. image::"):
            src = line.strip()[len(".. image::") :].strip()
            # Guide RST files use ../static/description/ prefix; strip it so the
            # path is relative to static/description/index.html at render time.
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
            html_parts.append(f'      <div style="text-align:center; margin:24px 0;"><img src="{html.escape(src)}" alt="{alt}" style="max-width:100%; height:auto; border-radius:6px;"/></div>')
            continue

        # -- other directives (skip block) ------------------------------------
        if line.strip().startswith(".. "):
            i += 1
            while i < n and (lines[i].startswith("   ") or not lines[i].strip()):
                i += 1
            continue

        # -- bullet list -------------------------------------------------------
        if re.match(r"^\s*[-*]\s", line):
            items: list[str] = []
            while i < n:
                stripped = lines[i].strip()
                m = re.match(r"^[-*]\s+(.*)", stripped)
                if m:
                    items.append(m.group(1))
                    i += 1
                    # continuation lines indented 2+ spaces
                    while i < n and lines[i].startswith("  ") and not re.match(r"^\s*[-*]\s", lines[i]):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                elif not stripped:
                    break
                else:
                    break
            lis = "\n".join(f'        <li style="margin-bottom:6px;">{_strip_rst(item)}</li>' for item in items)
            html_parts.append(f"      <ul style=\"color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7; padding-left:24px; margin:0 0 16px;\">\n{lis}\n      </ul>")
            continue

        # -- numbered list -----------------------------------------------------
        if re.match(r"^\s*\d+\.\s", line):
            items = []
            while i < n:
                stripped = lines[i].strip()
                m = re.match(r"^\d+\.\s+(.*)", stripped)
                if m:
                    items.append(m.group(1))
                    i += 1
                    # continuation lines indented 3+ spaces
                    while i < n and lines[i].startswith("   ") and not re.match(r"^\s*\d+\.\s", lines[i]):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                elif not stripped:
                    break
                else:
                    break
            lis = "\n".join(f'        <li style="margin-bottom:8px;">{_strip_rst(item)}</li>' for item in items)
            html_parts.append(f"      <ol style=\"color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7; padding-left:24px; margin:0 0 16px;\">\n{lis}\n      </ol>")
            continue

        # -- paragraph (may end with :: intro for a code block) ----------------
        para_lines: list[str] = []
        while i < n and lines[i].strip() and not re.match(r"^\s*[-*]\s", lines[i]) and not re.match(r"^\s*\d+\.\s", lines[i]):
            para_lines.append(lines[i].rstrip())
            i += 1

        if not para_lines:
            i += 1
            continue

        full_text = " ".join(line.strip() for line in para_lines)

        if full_text.rstrip().endswith("::"):
            # Code block: intro paragraph + indented block
            intro = full_text.rstrip()[:-2].strip()
            # skip blank lines before indented block
            while i < n and not lines[i].strip():
                i += 1
            # collect indented code lines
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
            # strip trailing blank lines
            while code_lines and not code_lines[-1]:
                code_lines.pop()
            # remove common indentation
            indented = [line for line in code_lines if line.strip()]
            if indented:
                min_ind = min(len(line) - len(line.lstrip()) for line in indented)
                code_lines = [line[min_ind:] if line.strip() else "" for line in code_lines]
            code_content = html.escape("\n".join(code_lines)).replace("\u2014", "-").replace("\u2013", "-").replace("\u2192", "->")
            if intro:
                html_parts.append(_p(intro))
            html_parts.append(f"      <pre>{code_content}</pre>")
        else:
            html_parts.append(_p(full_text))

    content = "\n".join(html_parts)
    return f"""
<section class="oe_container" style="background:{bg_color}; padding:40px 0;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <h2 style="color:{BRAND_PRIMARY}; font-family:'Space Grotesk',sans-serif; font-size:22px; font-weight:700; margin-bottom:24px; padding-bottom:12px; border-bottom:2px solid {BRAND_MIST};">{guide_title}</h2>
{content}
    </div>
  </div>
</section>"""


def _copy_banners(repo_root: Path) -> None:
    banner_root = repo_root / "assets" / "banners"
    for addon in BANNER_ADDONS:
        source = banner_root / f"{addon}.png"
        if not source.exists():
            raise FileNotFoundError(f"Missing banner asset: {source}")
        target = repo_root / addon / "static" / "description" / "banner.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _copy_covers(repo_root: Path) -> None:
    cover_root = repo_root / "assets" / "covers"
    for addon in COVER_ADDONS:
        source = cover_root / f"{addon}.png"
        if not source.exists():
            raise FileNotFoundError(f"Missing cover asset: {source}")
        target = repo_root / addon / "static" / "description" / "cover.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


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

    parts = []

    # --- Hero ---
    parts.append(f"""
<section class="oe_container" style="background:{BRAND_CLOUD}; padding:40px 0 32px;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12" style="text-align:center;">
      <img src="cover.png" alt="{name} cover" style="max-width:960px; width:100%; border-radius:12px; box-shadow:0 10px 30px rgba(22,20,43,0.16);"/>
      <h2 class="oe_slogan" style="color:{BRAND_PRIMARY}; font-family:'Space Grotesk',sans-serif; margin-top:20px;">{name}</h2>
      <h3 class="oe_slogan" style="color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-weight:400;">{tagline}</h3>
    </div>
  </div>
</section>""")

    # --- Highlights ---
    if highlights:
        parts.append(f"""
<section class="oe_container" style="padding:40px 0;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <h2 style="color:{BRAND_PRIMARY}; font-family:'Space Grotesk',sans-serif;">Key Features</h2>
      <ul style="color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7;">
{_li(highlights)}
      </ul>
    </div>
  </div>
</section>""")

    # --- Diagrams ---
    for src, alt in diagrams:
        parts.append(f"""
<section class="oe_container oe_dark" style="background:{BRAND_MIST}; padding:32px 0; text-align:center;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <img src="{src}" alt="{alt}" style="max-width:720px; width:100%; border-radius:8px; box-shadow:0 2px 12px rgba(91,79,232,0.10);"/>
    </div>
  </div>
</section>""")

    # --- Configure ---
    if configure_steps:
        parts.append(f"""
<section class="oe_container" style="padding:40px 0;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <h2 style="color:{BRAND_PRIMARY}; font-family:'Space Grotesk',sans-serif;">Configuration</h2>
      <ol style="color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7;">
{_li(configure_steps)}
      </ol>
    </div>
  </div>
</section>""")

    # --- Usage ---
    if usage_steps:
        parts.append(f"""
<section class="oe_container" style="background:{BRAND_CLOUD}; padding:40px 0;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <h2 style="color:{BRAND_PRIMARY}; font-family:'Space Grotesk',sans-serif;">Usage</h2>
      <ol style="color:{BRAND_INK}; font-family:'IBM Plex Sans',sans-serif; font-size:15px; line-height:1.7;">
{_li(usage_steps)}
      </ol>
    </div>
  </div>
</section>""")

    # --- CTA ---
    if cta:
        parts.append(f"""
<section class="oe_container" style="background:{BRAND_PRIMARY}; padding:36px 0; text-align:center;">
  <div class="oe_row oe_spaced">
    <div class="oe_span12">
      <p style="color:#fff; font-family:'IBM Plex Sans',sans-serif; font-size:16px; margin:0;">{cta}</p>
    </div>
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
                BRAND_CLOUD,
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
                "#ffffff",
                skip_image_srcs=diagram_srcs,
            )
        )

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

    _copy_banners(repo_root)
    _copy_covers(repo_root)

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
