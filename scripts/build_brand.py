"""Write the Seen mark's brand files from one geometry (same as web/src/components/Eyes.tsx).

    uv run python scripts/build_brand.py      # needs rsvg-convert (brew install librsvg) for the PNGs

assets/brand/: eyes.svg (animated, dark-aware), eyes-static.svg, eyes-mono.svg, favicon-32.png, icon-192.png,
icon-512.png, social-preview.svg/.png. The SVGs and the 32/192 PNGs are copied to web/public/brand/.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"
PUBLIC = ROOT / "web" / "public" / "brand"
CY, EYES = 25, (18, 46)
TUFTS = ('<path class="tuft" d="M7 11 Q11 3.5 21 7.5 Q15 6.8 12.5 9.6 Q10 8.6 7 11 Z"/>'
         '<path class="tuft" d="M57 11 Q53 3.5 43 7.5 Q49 6.8 51.5 9.6 Q54 8.6 57 11 Z"/>')
IRIS = ('<radialGradient id="iris" cx="50%" cy="50%" r="55%"><stop offset="0" stop-color="#FFD27A"/>'
        '<stop offset=".45" stop-color="#F59A3E"/><stop offset=".85" stop-color="#E85D26"/>'
        '<stop offset="1" stop-color="#9E3A12"/></radialGradient>')
DARK = "@media (prefers-color-scheme: dark) { .ring { stroke: #F5F5F5; fill: #1A3A5C } }"


def lens(cx: float, open_: float = 0.9) -> str:
    h = 14.2 * open_
    return f"M{cx - 16},{CY} Q{cx},{CY - 2 * h:.2f} {cx + 16},{CY} Q{cx},{CY + 2 * h:.2f} {cx - 16},{CY} Z"


def mark(iris: str = "url(#iris)", pupil: str = "#0A2540", glints: bool = True, look: str = "look") -> str:
    out = []
    for i, cx in enumerate(EYES):
        g = f'<circle cx="{cx + 3}" cy="{CY - 3.6}" r="2.5" fill="#FFFFFF"/><circle cx="{cx - 2.6}" cy="{CY + 3.4}" r="1.1" fill="#FFFFFF"/>' if glints else ""
        out.append(f'<circle class="ring" cx="{cx}" cy="{CY}" r="13.2"/>'
                   f'<g clip-path="url(#c{i})"><g class="lids"><g clip-path="url(#l{i})"><circle cx="{cx}" cy="{CY}" r="13" fill="{iris}"/>'
                   f'<g class="{look}"><circle cx="{cx}" cy="{CY}" r="6.6" fill="{pupil}"/>{g}</g></g></g></g>')
    return "".join(out)


def clips() -> str:
    return "".join(f'<clipPath id="c{i}"><circle cx="{cx}" cy="{CY}" r="12.4"/></clipPath>'
                   f'<clipPath id="l{i}"><path d="{lens(cx)}"/></clipPath>' for i, cx in enumerate(EYES))


def svg(body: str, style: str, defs: str = "", vb: str = "0 -11 64 64", label: str = "Seen") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="{label}">\n'
            f'  <!-- Seen mark: owl eyes, amber-to-orange iris, navy pupil, orange tufts. Built by scripts/build_brand.py. -->\n'
            f'  <defs>{defs}{clips()}</defs>\n  <style>{style}</style>\n  {TUFTS}{body}\n</svg>\n')


BASE = ".ring { fill: #0A2540; stroke: #0A2540; stroke-width: 2 } .tuft { fill: #E85D26 } "
ANIM = ("""
    .look { animation: look 9s cubic-bezier(.2,1,.3,1) infinite }
    .lids { transform-box: fill-box; transform-origin: center; animation: blink 5.2s infinite }
    @keyframes look { 0%,14% { transform: translate(0,0) } 16%,34% { transform: translate(-3.6px,.6px) }
      36%,52% { transform: translate(3.4px,-1.6px) } 54%,70% { transform: translate(1px,2.6px) } 72%,100% { transform: translate(0,0) } }
    @keyframes blink { 0%,93%,100% { transform: scaleY(1) } 95.5% { transform: scaleY(.06) } }
    @media (prefers-reduced-motion: reduce) { .look, .lids { animation: none } }""")


def main() -> None:
    files = {
        "eyes.svg": svg(mark(), BASE + DARK + ANIM, IRIS),
        "eyes-static.svg": svg(mark(), BASE + DARK, IRIS),
        "eyes-mono.svg": svg(mark(iris="#FFFFFF"), ".ring { fill: #0A2540; stroke: #0A2540; stroke-width: 2 } .tuft { fill: #0A2540 }"),
    }
    big = svg(mark(), BASE.replace("stroke: #0A2540", "stroke: #F5F5F5").replace("fill: #0A2540", "fill: #1A3A5C"), IRIS)
    inner = big.split("<defs>", 1)[1].rsplit("</svg>", 1)[0]
    files["social-preview.svg"] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640">\n  <rect width="1280" height="640" fill="#0A2540"/>\n'
        f'  <g transform="translate(96 152) scale(5.4)"><defs>{inner}</g>\n'
        '  <text x="480" y="335" font-family="IBM Plex Sans, Helvetica, sans-serif" font-size="150" font-weight="600" fill="#FFFFFF">Seen</text>\n'
        '  <text x="484" y="405" font-family="IBM Plex Sans, Helvetica, sans-serif" font-size="38" fill="#F5F5F5">Nothing your agents do goes unseen.</text>\n'
        '  <rect x="484" y="435" width="120" height="6" fill="#E85D26"/>\n'
        '  <text x="484" y="500" font-family="IBM Plex Mono, monospace" font-size="24" fill="#94A6BA">github.com/surenganne/seen</text>\n</svg>\n')
    for name, text in files.items():
        (OUT / name).write_text(text)
    rsvg = shutil.which("rsvg-convert")
    if not rsvg:
        raise SystemExit("SVGs written; PNGs need rsvg-convert (brew install librsvg)")
    for size, name in ((32, "favicon-32.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        subprocess.run([rsvg, "-w", str(size), "-h", str(size), "-o", str(OUT / name), str(OUT / "eyes-static.svg")], check=True)
    subprocess.run([rsvg, "-w", "1280", "-h", "640", "-o", str(OUT / "social-preview.png"), str(OUT / "social-preview.svg")], check=True)
    for name in ("eyes.svg", "eyes-static.svg", "eyes-mono.svg", "favicon-32.png", "icon-192.png"):
        shutil.copy2(OUT / name, PUBLIC / name)
    print("wrote", ", ".join(sorted([*files, "favicon-32.png", "icon-192.png", "icon-512.png", "social-preview.png"])))


if __name__ == "__main__":
    main()
