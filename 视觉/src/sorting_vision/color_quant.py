"""Dominant color extraction ported from node-vibrant (MMCQ).

Ported from the following TypeScript sources in node-vibrant:

- packages/vibrant-image/src/histogram.ts
- packages/vibrant-quantizer-mmcq/src/vbox.ts
- packages/vibrant-quantizer-mmcq/src/index.ts
- packages/vibrant-color/src/converter.ts (RGB <-> HSL)

Purpose: given an RGBA byte buffer for one cropped item ROI, return the
dominant color(s) and a coarse hue-based color name. This is the
color-classification fallback that needs no trained model and adapts to
unseen colors.

The module is stdlib-only and has no dependency on the rest of
``sorting_vision``, so it can be imported and run standalone.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

RGB = Tuple[int, int, int]
Swatch = Tuple[RGB, int]

_SIG_BITS = 5
_RSHIFT = 8 - _SIG_BITS
_HIST_LEN = 1 << (3 * _SIG_BITS)  # 32768
_CH = {"r": (0, 1), "g": (2, 3), "b": (4, 5)}


def _color_index(r: int, g: int, b: int) -> int:
    return (r << (2 * _SIG_BITS)) + (g << _SIG_BITS) + b


def _build_histogram(pixels: Sequence[int]):
    """Build a 5-bit/channel histogram over an RGBA byte buffer."""

    hist = [0] * _HIST_LEN
    rmin = gmin = bmin = 1 << 30
    rmax = gmax = bmax = 0
    count = len(pixels) // 4
    visible_pixels = 0

    for i in range(count):
        o = i * 4
        r = pixels[o] >> _RSHIFT
        g = pixels[o + 1] >> _RSHIFT
        b = pixels[o + 2] >> _RSHIFT
        a = pixels[o + 3]
        if a == 0:
            continue
        visible_pixels += 1
        idx = _color_index(r, g, b)
        hist[idx] += 1
        if r > rmax:
            rmax = r
        if r < rmin:
            rmin = r
        if g > gmax:
            gmax = g
        if g < gmin:
            gmin = g
        if b > bmax:
            bmax = b
        if b < bmin:
            bmin = b

    return {
        "hist": hist,
        "rmin": rmin,
        "rmax": rmax,
        "gmin": gmin,
        "gmax": gmax,
        "bmin": bmin,
        "bmax": bmax,
        "visible_pixels": visible_pixels,
    }


class _VBox:
    """A box in RGB space over the quantized histogram."""

    def __init__(self, dim: Sequence[int], histogram):
        # dim = [r1, r2, g1, g2, b1, b2] in quantized space (0..31).
        self.dim = list(dim)
        self.histogram = histogram
        self._volume = -1
        self._count = -1
        self._avg = None

    def _lo(self, channel: str) -> int:
        return self.dim[_CH[channel][0]]

    def _hi(self, channel: str) -> int:
        return self.dim[_CH[channel][1]]

    def volume(self) -> int:
        if self._volume < 0:
            self._volume = (
                (self._hi("r") - self._lo("r") + 1)
                * (self._hi("g") - self._lo("g") + 1)
                * (self._hi("b") - self._lo("b") + 1)
            )
        return self._volume

    def count(self) -> int:
        if self._count < 0:
            hist = self.histogram["hist"]
            total = 0
            for r in range(self._lo("r"), self._hi("r") + 1):
                for g in range(self._lo("g"), self._hi("g") + 1):
                    for b in range(self._lo("b"), self._hi("b") + 1):
                        total += hist[_color_index(r, g, b)]
            self._count = total
        return self._count

    def clone(self) -> "_VBox":
        return _VBox(self.dim, self.histogram)

    def avg(self) -> RGB:
        if self._avg is None:
            hist = self.histogram["hist"]
            mult = 1 << (8 - _SIG_BITS)
            ntot = 0
            rsum = gsum = bsum = 0
            for r in range(self._lo("r"), self._hi("r") + 1):
                for g in range(self._lo("g"), self._hi("g") + 1):
                    for b in range(self._lo("b"), self._hi("b") + 1):
                        h = hist[_color_index(r, g, b)]
                        if not h:
                            continue
                        ntot += h
                        rsum += h * (r + 0.5) * mult
                        gsum += h * (g + 0.5) * mult
                        bsum += h * (b + 0.5) * mult
            if ntot:
                self._avg = (int(rsum / ntot), int(gsum / ntot), int(bsum / ntot))
            else:
                r1, g1, b1 = self._lo("r"), self._lo("g"), self._lo("b")
                r2, g2, b2 = self._hi("r"), self._hi("g"), self._hi("b")
                self._avg = (
                    int(mult * (r1 + r2 + 1) / 2),
                    int(mult * (g1 + g2 + 1) / 2),
                    int(mult * (b1 + b2 + 1) / 2),
                )
        return self._avg

    def split(self):
        """Median-cut split along the widest channel; returns (left, right)."""

        hist = self.histogram["hist"]
        count = self.count()
        if not count:
            return None
        if count == 1:
            return (self.clone(), None)

        r1, r2 = self._lo("r"), self._hi("r")
        g1, g2 = self._lo("g"), self._hi("g")
        b1, b2 = self._lo("b"), self._hi("b")
        rw, gw, bw = r2 - r1 + 1, g2 - g1 + 1, b2 - b1 + 1
        maxw = max(rw, gw, bw)

        total = 0
        acc_sum = None
        if maxw == rw:
            maxd = "r"
            acc_sum = [0] * (r2 + 1)
            for r in range(r1, r2 + 1):
                s = 0
                for g in range(g1, g2 + 1):
                    for b in range(b1, b2 + 1):
                        h = hist[_color_index(r, g, b)]
                        if h:
                            s += h
                total += s
                acc_sum[r] = total
        elif maxw == gw:
            maxd = "g"
            acc_sum = [0] * (g2 + 1)
            for g in range(g1, g2 + 1):
                s = 0
                for r in range(r1, r2 + 1):
                    for b in range(b1, b2 + 1):
                        h = hist[_color_index(r, g, b)]
                        if h:
                            s += h
                total += s
                acc_sum[g] = total
        else:
            maxd = "b"
            acc_sum = [0] * (b2 + 1)
            for b in range(b1, b2 + 1):
                s = 0
                for r in range(r1, r2 + 1):
                    for g in range(g1, g2 + 1):
                        h = hist[_color_index(r, g, b)]
                        if h:
                            s += h
                total += s
                acc_sum[b] = total

        split_point = -1
        reverse_sum = [0] * len(acc_sum)
        for i, d in enumerate(acc_sum):
            if not d:
                continue
            if split_point < 0 and d > total / 2:
                split_point = i
            reverse_sum[i] = total - d

        lo_idx, hi_idx = _CH[maxd]
        d1 = self.dim[lo_idx]
        d2 = self.dim[hi_idx]
        left = split_point - d1
        right = d2 - split_point

        if left <= right:
            d2 = min(d2 - 1, int(split_point + right / 2))
            d2 = max(0, d2)
        else:
            d2 = max(d1, int(split_point - 1 - left / 2))
            d2 = min(self.dim[hi_idx], d2)

        while d2 < len(acc_sum) and not acc_sum[d2]:
            d2 += 1
        c2 = reverse_sum[d2] if d2 < len(reverse_sum) else 0
        while not c2 and d2 - 1 >= 0 and acc_sum[d2 - 1]:
            d2 -= 1
            c2 = reverse_sum[d2]

        box1 = self.clone()
        box2 = self.clone()
        box1.dim[hi_idx] = d2
        box2.dim[lo_idx] = d2 + 1
        return (box1, box2)


class _PQueue:
    """Tiny priority queue whose ``pop`` returns the largest key first."""

    def __init__(self, key):
        self._key = key
        self.contents: List[_VBox] = []
        self._sorted = False

    def push(self, item: _VBox) -> None:
        self.contents.append(item)
        self._sorted = False

    def _sort(self) -> None:
        if not self._sorted:
            self.contents.sort(key=self._key)
            self._sorted = True

    def pop(self):
        self._sort()
        return self.contents.pop() if self.contents else None

    def size(self) -> int:
        return len(self.contents)


def _split_boxes(pq: _PQueue, target: int) -> None:
    last_size = pq.size()
    while pq.size() < target:
        box = pq.pop()
        if box is None or box.count() <= 0:
            break
        parts = box.split()
        if parts is None or parts[0] is None:
            break
        box1, box2 = parts
        pq.push(box1)
        if box2 is not None and box2.count() > 0:
            pq.push(box2)
        if pq.size() == last_size:
            break
        last_size = pq.size()


def mmcq(pixels: Sequence[int], color_count: int = 6) -> List[Swatch]:
    """Return ``[(rgb, population), ...]`` using modified median cut."""

    if (
        not isinstance(color_count, int)
        or isinstance(color_count, bool)
        or color_count < 2
        or color_count > 256
    ):
        raise ValueError("MMCQ requires pixels and 2 <= color_count <= 256")
    if not pixels or len(pixels) % 4:
        raise ValueError("MMCQ requires a complete RGBA pixel buffer")

    histogram = _build_histogram(pixels)
    if histogram["visible_pixels"] == 0:
        raise ValueError("MMCQ requires at least one visible pixel")
    dim = [
        histogram["rmin"],
        histogram["rmax"],
        histogram["gmin"],
        histogram["gmax"],
        histogram["bmin"],
        histogram["bmax"],
    ]
    vbox = _VBox(dim, histogram)

    pq = _PQueue(key=lambda v: v.count())
    pq.push(vbox)
    _split_boxes(pq, int(0.75 * color_count))

    pq2 = _PQueue(key=lambda v: v.count() * v.volume())
    pq2.contents = list(pq.contents)
    _split_boxes(pq2, color_count)

    swatches: List[Swatch] = []
    while pq2.size():
        v = pq2.pop()
        swatches.append((v.avg(), v.count()))
    return swatches


def dominant_color(pixels: Sequence[int], color_count: int = 6) -> RGB:
    """Return the RGB of the most populous swatch."""

    swatches = mmcq(pixels, color_count)
    swatches.sort(key=lambda s: s[1], reverse=True)
    return swatches[0][0]


def rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Return ``(h, s, l)`` with ``h`` in ``[0, 1]``."""

    r, g, b = r / 255.0, g / 255.0, b / 255.0
    hi = max(r, g, b)
    lo = min(r, g, b)
    l = (hi + lo) / 2
    if hi == lo:
        h = s = 0.0
    else:
        d = hi - lo
        s = d / (2 - hi - lo) if l > 0.5 else d / (hi + lo)
        if hi == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif hi == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return (h, s, l)


def color_name(rgb: RGB) -> str:
    """Coarse hue/lightness bucketing for common colors.

    This is a starter mapping to be calibrated against the real lighting and
    white-balance setup; the HSV thresholds should be frozen only after an
    on-site calibration pass.
    """

    h, s, l = rgb_to_hsl(*rgb)
    if s < 0.12:
        if l < 0.15:
            return "black"
        if l > 0.85:
            return "white"
        return "gray"

    hue = h * 360
    if hue < 15 or hue >= 345:
        return "red"
    if hue < 45:
        return "orange"
    if hue < 70:
        return "yellow"
    if hue < 165:
        return "green"
    if hue < 200:
        return "cyan"
    if hue < 255:
        return "blue"
    if hue < 285:
        return "purple"
    return "pink"


if __name__ == "__main__":
    import random

    random.seed(0)
    width = height = 32
    pixels: List[int] = []
    for _ in range(width * height):
        if random.random() < 0.85:
            pixels += [205, 25, 25, 255]
        else:
            pixels += [25, 175, 60, 255]

    for swatch in mmcq(pixels, 4):
        print(swatch, color_name(swatch[0]))
    print("dominant", dominant_color(pixels, 4), color_name(dominant_color(pixels, 4)))
