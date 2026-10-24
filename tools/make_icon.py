"""Build the Windows icon for CatsVsMice.exe from cat_idle.png.

The plate is a loaf cat: head centred, ears at its outer edges, paws below it. A
whole-body plate turns into a grey smudge at 32 px, so the icon is the FACE cropped
to a square and set on the daytime plate's own sky with rounded corners.

Crop geometry is pinned by measured fractions of the silhouette bbox, anchored on the
green eyes (the only colour-separable feature in this art), so a re-rolled plate whose
face sits elsewhere still crops the face -- and if features vanish entirely the tool
says so instead of shipping a body crop.

Run:  python tools/make_icon.py            -> assets/generated/icon.ico
      python tools/make_icon.py --preview PATH   -> also dump the 256 px master PNG
"""
import os
import sys

import numpy as np
import pygame
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import renderer_assets

MASTER_SIZE = 256
ICON_SIZES = (16, 32, 48, 256)
CROP_ALPHA = 240          # same threshold the cloud crop uses: below it is key bleed
FACE_HALF_W = 0.342       # half the crop side, as a fraction of the silhouette width
FACE_BELOW_EYES = 0.20    # crop extends this far below the eye band (muzzle + chin)
FACE_FILL = 0.88          # crop square as a fraction of the tile side; the rest is sky
CORNER_RADIUS = 46        # rounded corners at MASTER_SIZE, scaled down with the tile


def _surface_to_pil(surf):
    """pygame Surface -> PIL RGBA image in [y][x] order."""
    rgb = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
    alpha = pygame.surfarray.array_alpha(surf).transpose(1, 0)
    return Image.fromarray(np.concatenate([rgb, alpha[..., None]], axis=2).astype(np.uint8))


def face_crop():
    """Square crop of cat_idle.png around the face, at plate resolution.

    Centred on the eye columns, spanning ear tips to chin. Raises if the eyes are not
    found rather than guessing a band that might be body fur.
    """
    surf = renderer_assets.matted_surface("cat_idle")
    al = pygame.surfarray.pixels_alpha(surf).transpose(1, 0)          # [y][x]
    rgb = pygame.surfarray.array3d(surf).transpose(1, 0, 2).astype(np.int32)
    solid = al >= CROP_ALPHA
    ys, xs = np.nonzero(solid)
    bx0, bx1, by0, by1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1

    green = (rgb[..., 1] > rgb[..., 0] + 30) & (rgb[..., 1] > rgb[..., 2] + 20) & solid
    cols = np.nonzero(green.any(axis=0))[0]
    rows = np.nonzero(green.any(axis=1))[0]
    if len(cols) == 0 or len(rows) == 0:
        raise RuntimeError("cat_idle.png has no green eyes to anchor the face crop on")
    cx = int((cols.min() + cols.max()) // 2)
    eye_bottom = int(rows.max())

    top = by0                                    # ear tips / head crown at the silhouette top
    bottom = min(by1, eye_bottom + int(round(FACE_BELOW_EYES * bh)))
    side = max(bottom - top + 1, int(round(2 * FACE_HALF_W * bw)))
    half = side // 2
    left = min(max(cx - half, bx0), bx1 - side + 1)
    top = min(max(top - (side - (bottom - top + 1)) // 2, by0), by1 - side + 1)
    rect = pygame.Rect(left, top, side, side)
    return surf.subsurface(rect).copy()


def tile_master(size=MASTER_SIZE):
    """The icon tile: face crop centred on the daytime plate's sky, rounded corners.

    Composited in numpy rather than with PIL's `paste`, so feathered edge pixels blend
    against the sky instead of landing on an alpha-0 base and vanishing.
    """
    plate = renderer_assets._plate_surface("bg_daytime")
    pa = pygame.surfarray.array3d(plate).transpose(1, 0, 2)          # [y][x][3]
    mid = pa.shape[1] // 2
    sky_top = pa[4, mid].astype(np.float32)
    sky_low = pa[int(pa.shape[0] * 0.30), mid].astype(np.float32)

    t = np.linspace(0.0, 1.0, size, dtype=np.float32)
    grad = np.round(sky_top[None, :] * (1.0 - t[:, None]) + sky_low[None, :] * t[:, None])
    rgb = np.repeat(grad[:, None, :], size, axis=1)                 # [y][x][3], rows vary

    # rounded corners, antialiased by sampling the corner arc at 4x then averaging down
    r = CORNER_RADIUS * size / float(MASTER_SIZE)
    ss = size * 4
    rs = r * 4.0
    gy, gx = np.meshgrid(np.arange(ss) + 0.5, np.arange(ss) + 0.5, indexing="ij")
    ccx = np.where(gx < ss / 2.0, rs, ss - rs)
    ccy = np.where(gy < ss / 2.0, rs, ss - rs)
    in_corner = ((gx < rs) & (gy < rs)) | ((gx > ss - rs) & (gy < rs)) \
        | ((gx < rs) & (gy > ss - rs)) | ((gx > ss - rs) & (gy > ss - rs))
    dist = np.hypot(gx - ccx, gy - ccy)
    alpha_ss = np.where(in_corner, (dist <= rs).astype(np.float32), 1.0)
    alpha = alpha_ss.reshape(size, 4, size, 4).mean(axis=(1, 3))

    side = int(round(size * FACE_FILL))
    face = np.asarray(_surface_to_pil(
        renderer_assets.clean_scale(face_crop(), (side, side)))).astype(np.float32)
    pad = (size - side) // 2
    fa = face[..., 3] / 255.0
    win = rgb[pad:pad + side, pad:pad + side]
    blended = win * (1.0 - fa[:, :, None]) + face[..., :3] * fa[:, :, None]
    rgb[pad:pad + side, pad:pad + side] = blended
    alpha[pad:pad + side, pad:pad + side] = np.maximum(
        alpha[pad:pad + side, pad:pad + side], fa)

    out = np.concatenate([np.round(rgb).astype(np.uint8),
                          np.round(alpha * 255).astype(np.uint8)[..., None]], axis=2)
    return Image.fromarray(out)


def write_ico(path, master=None, sizes=ICON_SIZES):
    """Pack PNG-compressed frames into an ICO container (modern Windows reads these)."""
    from io import BytesIO
    master = master or tile_master(max(sizes))
    payloads = []
    for side in sizes:
        buf = BytesIO()
        master.resize((side, side), Image.LANCZOS).save(buf, format="PNG")
        payloads.append(buf.getvalue())

    header = b"\x00\x00\x01\x00" + len(sizes).to_bytes(2, "little")
    offset = 6 + 16 * len(sizes)
    entries = []
    for side, payload in zip(sizes, payloads):
        w = side if side < 256 else 0
        h = side if side < 256 else 0
        entries += [w.to_bytes(1, "little"), h.to_bytes(1, "little"), b"\x00\x00",
                    b"\x01\x00", b"\x20\x00", len(payload).to_bytes(4, "little"),
                    offset.to_bytes(4, "little")]
        offset += len(payload)
    with open(path, "wb") as fh:
        fh.write(header + b"".join(entries) + b"".join(payloads))
    return path


def main(argv=None):
    argv = argv or sys.argv[1:]
    pygame.init()
    preview = None
    if "--preview" in argv:
        i = argv.index("--preview")
        preview = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    master = tile_master(MASTER_SIZE)
    if preview:
        master.save(preview, format="PNG")
    path = os.path.join(REPO, "assets", "generated", "icon.ico")
    write_ico(path, master)
    print(f"wrote {path} | sizes {ICON_SIZES} | {os.path.getsize(path):,} B")
    return path


if __name__ == "__main__":
    main()
