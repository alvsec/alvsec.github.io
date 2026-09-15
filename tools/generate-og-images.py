#!/usr/bin/env python3
"""
Genera las imágenes de vista previa (Open Graph) de static/img/.

Son las que se ven al compartir un enlace en LinkedIn o WhatsApp. Miden
1200x630, que es la proporción que esperan casi todas las redes.

Uso:
    python3 tools/generate-og-images.py

Requiere Pillow:  pip3 install Pillow

Para añadir una sección nueva, mete una entrada en VARIANTS y luego declara
la imagen en el front matter de esa página:

    ogImage: "img/og-loquesea.png"

Si no se declara nada, la página usa params.ogImage de hugo.toml.
"""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Falta Pillow. Instálalo con: pip3 install Pillow")

# Paleta, la misma que static/css/style.css
BG = (250, 249, 247)
FG = (22, 32, 46)
DIM = (85, 96, 110)
ACCENT = (180, 83, 9)
BORDER = (224, 220, 212)

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "img")

# Rutas de fuentes por orden de preferencia. La primera que exista, se usa.
BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REG_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def pick(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    sys.exit("No se encontró ninguna fuente utilizable. Edita las listas de candidatos.")


BOLD, REG = pick(BOLD_CANDIDATES), pick(REG_CANDIDATES)


def node_tree(d, cx, cy, s, line, root, leaf, w):
    """La marca: árbol de dominio, raíz arriba y dos hojas abajo."""
    ry, ly = cy - s, cy + s
    lx1, lx2 = cx - s, cx + s
    d.line([(cx, ry), (cx, cy)], fill=line, width=w)
    d.line([(lx1, cy), (lx2, cy)], fill=line, width=w)
    d.line([(lx1, cy), (lx1, ly)], fill=line, width=w)
    d.line([(lx2, cy), (lx2, ly)], fill=line, width=w)
    r1, r2 = int(s * 0.42), int(s * 0.36)
    d.ellipse([cx - r1, ry - r1, cx + r1, ry + r1], fill=root)
    for x in (lx1, lx2):
        d.ellipse([x - r2, ly - r2, x + r2, ly + r2], fill=leaf)


# nombre de archivo -> (línea 1, línea 2, subtítulo)
VARIANTS = {
    "og-default.png": (
        "Security audits for small",
        "businesses and local shops",
        "Offensive testing and defensive review",
    ),
    "og-es.png": (
        "Auditorías de seguridad para",
        "pymes y comercio local",
        "Pruebas ofensivas y revisión defensiva",
    ),
    "og-portfolio.png": (
        "Intrusion writeups and",
        "audit reports",
        "Published technical work you can check yourself",
    ),
    "og-portfolio-es.png": (
        "Writeups de intrusión e",
        "informes de auditoría",
        "Trabajo técnico publicado que puedes revisar",
    ),
}


def build(name, l1, l2, sub):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, 14, H], fill=ACCENT)          # banda de acento
    d.rectangle([14, 0, W - 1, H - 1], outline=BORDER, width=1)

    x = 78
    node_tree(d, x + 19, 88, 19, FG, ACCENT, FG, 4)  # marca

    brand_f = ImageFont.truetype(BOLD, 34)
    d.text((x + 58, 71), "DOMAIN", font=brand_f, fill=FG)
    bw = d.textlength("DOMAIN ", font=brand_f)
    d.text((x + 58 + bw, 71), "SECURITY", font=brand_f, fill=ACCENT)

    head_f = ImageFont.truetype(BOLD, 62)
    d.text((x, 196), l1, font=head_f, fill=FG)
    d.text((x, 274), l2, font=head_f, fill=FG)

    d.rectangle([x, 380, x + 84, 385], fill=ACCENT)  # regla de acento
    d.text((x, 418), sub, font=ImageFont.truetype(REG, 30), fill=DIM)

    foot_f = ImageFont.truetype(REG, 26)
    d.text((x, 522), "Álvaro Irún", font=foot_f, fill=FG)
    d.text((x, 556), "domainsecurity.agency", font=foot_f, fill=DIM)

    path = os.path.join(OUT, name)
    img.save(path, "PNG", optimize=True)
    print(f"  {name}  {img.size[0]}x{img.size[1]}  {os.path.getsize(path) // 1024} KB")


# ---------------------------------------------------------------------------
# Portada de perfil de LinkedIn: 1584x396.
# La foto de perfil se superpone abajo a la izquierda, así que esa esquina se
# deja despejada a propósito y el texto arranca desplazado a la derecha.
# ---------------------------------------------------------------------------

BANNER = (1584, 396)
BANNER_SUB = "Auditorías de seguridad y test de intrusión para pymes"
BANNER_FOOT = "Álvaro Irún  ·  La Safor, Valencia"


def build_banner(name="linkedin-cover.png"):
    bw, bh = BANNER
    img = Image.new("RGB", (bw, bh), FG)
    d = ImageDraw.Draw(img)

    # Marca de agua grande y muy tenue a la derecha
    node_tree(d, 1285, 198, 104, (34, 47, 66), (43, 58, 79), (34, 47, 66), 12)
    d.rectangle([0, 0, bw, 7], fill=ACCENT)

    x = 430
    node_tree(d, x + 26, 128, 26, BG, ACCENT, BG, 5)

    brand_f = ImageFont.truetype(BOLD, 44)
    d.text((x + 76, 106), "DOMAIN", font=brand_f, fill=BG)
    bwid = d.textlength("DOMAIN ", font=brand_f)
    d.text((x + 76 + bwid, 106), "SECURITY", font=brand_f, fill=ACCENT)

    d.text((x, 200), BANNER_SUB, font=ImageFont.truetype(REG, 29), fill=(169, 180, 195))
    d.rectangle([x, 258, x + 78, 263], fill=ACCENT)

    foot_f = ImageFont.truetype(REG, 25)
    d.text((x, 292), BANNER_FOOT, font=foot_f, fill=(169, 180, 195))
    d.text((x, 330), "domainsecurity.agency", font=foot_f, fill=(200, 210, 224))

    path = os.path.join(OUT, name)
    img.save(path, "PNG", optimize=True)
    print(f"  {name}  {bw}x{bh}  {os.path.getsize(path) // 1024} KB")


if __name__ == "__main__":
    print("Generando imágenes Open Graph:")
    for name, parts in VARIANTS.items():
        build(name, *parts)
    build_banner()
