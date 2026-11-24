"""
Synthetic image generator for the near-duplicate and privacy evaluations.

  category  = a scene "template" (layout of big shapes + palette)  -> semantic label
  base image = template + random small objects                      -> one photo
  variant    = base image after resize / JPEG / crop / brightness   -> near-duplicate

Images of the same category share their coarse structure, so their dHash bands
collide more often than images of different categories. That is exactly the
"semantic neighbourhood" structure that Paper 3's attack exploits.
Use --dir in the scripts to evaluate on your own photos instead.
"""
import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

W, H = 320, 240


def template(cat: int) -> dict:
    rnd = random.Random(1000 + cat)
    bg_top = tuple(rnd.randint(0, 255) for _ in range(3))
    bg_bottom = tuple(rnd.randint(0, 255) for _ in range(3))
    shapes = []
    for _ in range(rnd.randint(3, 5)):
        x, y = rnd.randint(0, W - 80), rnd.randint(0, H - 60)
        shapes.append((rnd.choice(["rect", "ellipse"]), x, y, x + rnd.randint(60, 160),
                       y + rnd.randint(40, 120), tuple(rnd.randint(0, 255) for _ in range(3))))
    return {"top": bg_top, "bottom": bg_bottom, "shapes": shapes, "horizon": rnd.randint(80, 170)}


def base_image(cat: int, idx: int, jitter: int = 30) -> Image.Image:
    t = template(cat)
    rnd = random.Random(cat * 100003 + idx)
    img = Image.new("RGB", (W, H), t["top"])
    d = ImageDraw.Draw(img)
    hz = t["horizon"] + rnd.randint(-15, 15)
    d.rectangle([0, hz, W, H], fill=t["bottom"])
    for kind, x0, y0, x1, y1, col in t["shapes"]:
        dx, dy = rnd.randint(-jitter, jitter), rnd.randint(-jitter, jitter)
        col = tuple(max(0, min(255, c + rnd.randint(-40, 40))) for c in col)
        box = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
        (d.rectangle if kind == "rect" else d.ellipse)(box, fill=col)
    for _ in range(rnd.randint(4, 12)):                     # small unique details
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(4, 18)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return img.filter(ImageFilter.GaussianBlur(1))


def _jpeg(img, q):
    b = io.BytesIO()
    img.save(b, "JPEG", quality=q)
    b.seek(0)
    return Image.open(b).convert("RGB")


TRANSFORMS = {
    "resize_50": lambda im: im.resize((im.width // 2, im.height // 2)),
    "resize_25": lambda im: im.resize((im.width // 4, im.height // 4)),
    "jpeg_q50": lambda im: _jpeg(im, 50),
    "jpeg_q20": lambda im: _jpeg(im, 20),
    "crop_5": lambda im: im.crop((int(im.width * .05), int(im.height * .05),
                                   int(im.width * .95), int(im.height * .95))),
    "crop_15": lambda im: im.crop((int(im.width * .15), int(im.height * .15),
                                    int(im.width * .85), int(im.height * .85))),
    "brightness_+20": lambda im: ImageEnhance.Brightness(im).enhance(1.2),
    "blur": lambda im: im.filter(ImageFilter.GaussianBlur(2)),
    "rotate_3": lambda im: im.rotate(3, expand=False),
    "hflip": lambda im: im.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
}


def random_variant(img: Image.Image, rnd: random.Random) -> Image.Image:
    """A realistic re-upload: 1-2 mild transformations."""
    mild = ["resize_50", "jpeg_q50", "crop_5", "brightness_+20", "blur"]
    for name in rnd.sample(mild, rnd.randint(1, 2)):
        img = TRANSFORMS[name](img)
    return img
