"""Cut butler frames from the sprite sheet into normalized animation strips.

    python tools/cut_sprites.py apps/desktop/assets-src/butler-sprite-sheet.png apps/desktop/public/butler /tmp/contact.png

Needs: pip install pillow numpy scipy
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

SRC = sys.argv[1]; OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
sheet = Image.open(SRC).convert("RGBA")
A = np.array(sheet)

# (x0, x1) columns per frame; y band per row (excludes headers above and labels below)
ROW_IDLE   = (33, 232)
ROW_WALK   = (290, 437)
ROW_ACTION = (650, 825)
ROW_ACTION_L = (677, 825)  # left of row has the section header
ROW_FACE   = (878, 990)
ROW_SLEEP  = (868, 1012)

ANIMS = {
  # name: (y band, [x ranges], target figure height in px @1x, fps)
  "idle":    (ROW_IDLE,   [(1010, 1120), (1135, 1245), (1010, 1120), (1395, 1515)], 168, 1.2),
  "think":   (ROW_IDLE,   [(1262, 1385)], 168, 1),
  "walk_r":  (ROW_WALK,   [(24,116),(116,210),(210,292),(292,381),(381,467),(467,553),(553,635),(635,727)], 168, 10),
  "walk_l":  (ROW_WALK,   [(790,878),(878,970),(970,1060),(1060,1145),(1145,1232),(1232,1318),(1318,1410),(1410,1500)], 168, 10),
  "wave":    (ROW_ACTION_L, [(15, 135)], 168, 1),
  "point":   (ROW_ACTION_L, [(140, 272)], 168, 1),
  "bow":     (ROW_ACTION, [(278, 384)], 160, 1),
  "serve":   (ROW_ACTION, [(405, 530)], 168, 1),
  "phone":   (ROW_ACTION, [(1128, 1272)], 168, 1),
  "read":    (ROW_ACTION, [(836, 962)], 168, 1),
  "sleep":   (ROW_SLEEP,  [(1395, 1530)], 120, 1),
  "dust":    (ROW_ACTION, [(962, 1114)], 150, 1),
  "jump":    ((486, 645), [(1155, 1257, 503), (1257, 1350), (1343, 1442), (1425, 1530)], 168, 8),
}
FACES = {n: x for n, x in zip(
  ["happy","smile","neutral","surprised","confused","worried","angry","laugh","sleepy","blink","talk1","talk2"],
  [(18,102),(100,182),(184,262),(266,346),(354,432),(438,518),(525,605),(605,688),(693,775),(778,860),(860,940),(946,1028)])}

def figure(y, x):
    if len(x) == 3:  # (x0, x1, top) — per-frame top edge, e.g. to clear a section header
        y, x = (x[2], y[1]), x[:2]
    crop = A[y[0]:y[1], x[0]:x[1]]
    mask = crop[:, :, 3] > 30
    lab, n = ndimage.label(ndimage.binary_dilation(mask, iterations=2))
    if n == 0:
        raise ValueError(f"empty cell {x}")
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= 0.08 * sizes.max()]) & mask
    ys, xs = np.where(keep)
    out = crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1].copy()
    out[:, :, 3] = np.where(keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1], out[:, :, 3], 0)
    return Image.fromarray(out)

SCALE = 2                 # export @2x for Retina
CELL = (150, 190)         # @1x cell size in CSS px
manifest = {"cell": CELL, "scale": SCALE, "anims": {}}
for name, (yband, xs, target_h, fps) in ANIMS.items():
    frames = [figure(yband, x) for x in xs]
    ref_h = max(f.height for f in frames)
    k = target_h * SCALE / ref_h
    W, H = CELL[0] * SCALE, CELL[1] * SCALE
    strip = Image.new("RGBA", (W * len(frames), H), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        f = f.resize((max(1, round(f.width * k)), max(1, round(f.height * k))), Image.LANCZOS)
        if f.width > W:  # wide poses (chair, newspaper) shrink to fit the cell
            f = f.resize((W, round(f.height * W / f.width)), Image.LANCZOS)
        strip.alpha_composite(f, (i * W + (W - f.width) // 2, H - f.height - 4))
    strip.save(OUT / f"{name}.png", optimize=True)
    manifest["anims"][name] = {"frames": len(frames), "fps": fps, "file": f"{name}.png"}

faces = [figure(ROW_FACE, x) for x in FACES.values()]
FS = 96 * SCALE // 2  # faces @2x of 48px
fstrip = Image.new("RGBA", (FS * len(faces), FS), (0, 0, 0, 0))
for i, f in enumerate(faces):
    k = FS / max(f.width, f.height)
    f = f.resize((round(f.width * k), round(f.height * k)), Image.LANCZOS)
    fstrip.alpha_composite(f, (i * FS + (FS - f.width) // 2, FS - f.height))
fstrip.save(OUT / "faces.png", optimize=True)
manifest["faces"] = {"size": FS // SCALE, "names": list(FACES)}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

# contact sheet for visual QA
rows = [Image.open(OUT / f"{n}.png") for n in ANIMS] + [fstrip]
cs = Image.new("RGBA", (max(r.width for r in rows), sum(r.height + 10 for r in rows)), (235, 230, 220, 255))
yy = 0
for r in rows:
    cs.alpha_composite(r, (0, yy)); yy += r.height + 10
cs.convert("RGB").resize((cs.width // 3, cs.height // 3)).save(sys.argv[3])
print("ok", {n: m["frames"] for n, m in manifest["anims"].items()})
