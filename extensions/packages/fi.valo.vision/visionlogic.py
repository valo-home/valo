"""Распознавание объектов на кадре моделью YOLOX и фильтр по меткам, порогу и зонам."""

import hashlib
import io
import pathlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MODEL = pathlib.Path(__file__).with_name("model") / "yolox_tiny.onnx"
MODEL_SHA256 = "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
SIZE = 416
STRIDES = (8, 16, 32)
IOU = 0.45
PAD = 114
ANIMALS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
LABELS = ("person", "car", "animal", "bicycle", "motorcycle", "truck", "bus")
COLORS = {"person": (255, 176, 32), "car": (64, 170, 255), "animal": (120, 220, 120)}


def label_of(cls: int) -> str | None:
    return "animal" if cls in ANIMALS else CLASSES.get(cls)


def verify(path: pathlib.Path = MODEL) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError(f"model {path.name} checksum mismatch: {digest}")


@dataclass
class Det:
    label: str
    score: float
    box: tuple[float, float, float, float]
    zone: str = ""

    def view(self) -> dict[str, Any]:
        return {"box": [round(v, 3) for v in self.box], "zone": self.zone, "score": round(self.score, 3)}


def letterbox(img: Image.Image, size: int = SIZE) -> tuple[np.ndarray, float]:
    """Кадр в вход модели: пропорциональное уменьшение, поле 114 справа и снизу, порядок BGR, NCHW float32."""
    r = min(size / img.width, size / img.height)
    w, h = max(1, round(img.width * r)), max(1, round(img.height * r))
    pad = np.full((size, size, 3), PAD, np.uint8)
    pad[:h, :w] = np.asarray(img.convert("RGB").resize((w, h), Image.Resampling.BILINEAR))
    return np.ascontiguousarray(pad[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32), r


def grids(size: int = SIZE) -> tuple[np.ndarray, np.ndarray]:
    gs, ss = [], []
    for st in STRIDES:
        n = size // st
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        gs.append(np.stack((xv, yv), 2).reshape(-1, 2))
        ss.append(np.full((n * n, 1), st))
    return np.concatenate(gs).astype(np.float32), np.concatenate(ss).astype(np.float32)


_GRID = grids()


def decode(
    out: np.ndarray, ratio: float, width: int, height: int, threshold: float
) -> list[tuple[int, float, list[float]]]:
    """Сырой выход YOLOX [1, N, 85] в рамки (класс, оценка, [x1, y1, x2, y2] в долях кадра)."""
    p = out[0] if out.ndim == 3 else out
    grid, stride = _GRID if p.shape[0] == _GRID[0].shape[0] else grids(round((p.shape[0] / 21) ** 0.5 * 32))
    xy = (p[:, :2] + grid) * stride
    wh = np.exp(np.clip(p[:, 2:4], -10, 10)) * stride
    scores = p[:, 4:5] * p[:, 5:]
    cls = scores.argmax(1)
    best = scores[np.arange(len(cls)), cls]
    keep = best >= threshold
    res = []
    for (cx, cy), (w, h), c, sc in zip(xy[keep], wh[keep], cls[keep], best[keep], strict=True):
        x1, y1 = (cx - w / 2) / ratio / width, (cy - h / 2) / ratio / height
        x2, y2 = (cx + w / 2) / ratio / width, (cy + h / 2) / ratio / height
        res.append(
            (int(c), float(sc), [max(0.0, float(x1)), max(0.0, float(y1)), min(1.0, float(x2)), min(1.0, float(y2))])
        )
    return res


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms(items: list[tuple[int, float, list[float]]], limit: float = IOU) -> list[tuple[int, float, list[float]]]:
    out: list[tuple[int, float, list[float]]] = []
    for it in sorted(items, key=lambda x: -x[1]):
        if all(o[0] != it[0] or iou(o[2], it[2]) < limit for o in out):
            out.append(it)
    return out


def inside(pt: tuple[float, float], poly: list[list[float]]) -> bool:
    """Точка внутри многоугольника, метод луча."""
    x, y = pt
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def zone_of(box: tuple[float, float, float, float] | list[float], zones: list[dict[str, Any]]) -> str | None:
    """Зона объекта по нижней середине рамки. None, если объект отброшен зонами."""
    foot = ((box[0] + box[2]) / 2, box[3])
    for z in zones:
        if z.get("kind") == "exclude" and inside(foot, z.get("points") or []):
            return None
    incl = [z for z in zones if z.get("kind") != "exclude"]
    if not incl:
        return ""
    for z in incl:
        if inside(foot, z.get("points") or []):
            return str(z.get("id") or "")
    return None


def select(raw: list[tuple[int, float, list[float]]], detect: dict[str, Any], zones: list[dict[str, Any]]) -> list[Det]:
    """Объекты нужных меток с оценкой не ниже порога, учтенные зонами. Дубли одной метки убираются NMS."""
    wanted = set(detect.get("labels") or []) or set(LABELS)
    limit = float(detect.get("score") or 0.55)
    names = sorted(wanted)
    mapped = []
    for c, sc, box in raw:
        label = label_of(c)
        if label in wanted and sc >= limit:
            mapped.append((names.index(label), sc, box))
    out = []
    for i, sc, box in nms(mapped):
        z = zone_of(box, zones)
        if z is not None:
            out.append(Det(names[i], sc, (box[0], box[1], box[2], box[3]), z))
    return out


def best(dets: list[Det]) -> dict[str, Det]:
    top: dict[str, Det] = {}
    for d in dets:
        if d.label not in top or d.score > top[d.label].score:
            top[d.label] = d
    return top


@dataclass
class Tracker:
    """Начало и конец событий по меткам: начало при первом обнаружении, конец после hold секунд без него."""

    hold: float
    active: dict[str, dict[str, Any]] = field(default_factory=dict)

    def step(self, dets: list[Det], now: float) -> tuple[list[Det], list[str]]:
        top = best(dets)
        started = [d for lb, d in top.items() if lb not in self.active]
        for lb, d in top.items():
            cur = self.active.setdefault(lb, {"since": now, "event": None, "score": d.score})
            cur["seen"] = now
            cur["score"] = max(cur["score"], d.score)
        ended = [lb for lb, cur in self.active.items() if now - cur["seen"] >= self.hold]
        for lb in ended:
            self.active.pop(lb, None)
        return started, ended

    def close(self) -> list[str]:
        labels = list(self.active)
        self.active.clear()
        return labels


def to_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def draw(data: bytes, dets: list[Det]) -> bytes:
    """Снимок с рамками и подписями в JPEG. Подпись латиницей, во встроенном шрифте Pillow нет кириллицы."""
    img = to_image(data)
    d = ImageDraw.Draw(img)
    w, h = img.size
    font = ImageFont.load_default(size=max(12, h // 32))
    line = max(2, h // 240)
    for det in dets:
        x1, y1, x2, y2 = det.box[0] * w, det.box[1] * h, det.box[2] * w, det.box[3] * h
        color = COLORS.get(det.label, (255, 90, 90))
        d.rectangle((x1, y1, x2, y2), outline=color, width=line)
        text = f"{det.label} {round(det.score * 100)}%"
        tb = d.textbbox((x1, y1), text, font=font)
        ty = max(0, y1 - (tb[3] - tb[1]) - 2 * line)
        d.rectangle((x1, ty, x1 + (tb[2] - tb[0]) + 2 * line, ty + (tb[3] - tb[1]) + 2 * line), fill=color)
        d.text((x1 + line, ty + line - (tb[1] - y1)), text, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Detector:
    """Модель YOLOX tiny через onnxruntime на процессоре, один поток."""

    def __init__(self, path: pathlib.Path = MODEL, threads: int = 1) -> None:
        import onnxruntime as ort

        verify(path)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name

    def run(self, data: bytes, threshold: float = 0.2) -> list[tuple[int, float, list[float]]]:
        img = to_image(data)
        x, r = letterbox(img)
        out = self.session.run(None, {self.input: x})[0]
        return decode(out, r, img.width, img.height, threshold)
