"""Render a small orthographic image from the same mesh as the catalogue viewer."""
import math
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


WIDTH, HEIGHT = 320, 216
AA = 2


def unit(vector):
    return vector / np.linalg.norm(vector)


VIEW = unit(np.array([.85, -1.35, .8]))
RIGHT = unit(np.cross([0, 0, 1], VIEW))
FRAME = np.column_stack((RIGHT, -np.cross(VIEW, RIGHT), VIEW))
LIGHT = unit(np.array([.3, -1., 1.3]))


def paint_triangle(rgba, depth, triangle, color):
    a, b, c = triangle
    ab, ac = b - a, c - a
    area = ab[0] * ac[1] - ab[1] * ac[0]
    if abs(area) < 1e-6:
        return
    left = max(0, math.floor(triangle[:, 0].min()))
    right = min(depth.shape[1], math.ceil(triangle[:, 0].max()) + 1)
    top = max(0, math.floor(triangle[:, 1].min()))
    bottom = min(depth.shape[0], math.ceil(triangle[:, 1].max()) + 1)
    iy, ix = np.ogrid[top:bottom, left:right]
    x, y = ix + .5 - a[0], iy + .5 - a[1]
    u = (x * ac[1] - y * ac[0]) / area
    v = (ab[0] * y - ab[1] * x) / area
    z = a[2] + u * ab[2] + v * ac[2]
    region = depth[top:bottom, left:right]
    pixels = rgba[top:bottom, left:right]
    visible = (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1.000001) & (z > region)
    region[visible] = z[visible]
    pixels[visible] = color


def render(mesh):
    parts = [(np.asarray(part['vertices'], dtype=float), np.asarray(part['triangles']), np.asarray(part['color']))
             for part in mesh['parts'] if part['vertices'] and part['triangles']]
    if not parts:
        raise ValueError('附件没有可渲染的网格')
    projected = [vertices @ FRAME for vertices, _, _ in parts]
    points = np.concatenate(projected)
    low, high = points.min(axis=0), points.max(axis=0)
    if not np.isfinite(points).all() or np.min(high[:2] - low[:2]) <= 0:
        raise ValueError('附件网格无法生成缩略图')
    size = np.array([WIDTH * AA, HEIGHT * AA])
    scale = min(size * .80 / (high[:2] - low[:2]))
    rgba = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    depth = np.full(rgba.shape[:2], -np.inf)

    for (vertices, indices, material), screen in zip(parts, projected):
        screen[:, :2] = (screen[:, :2] - (low[:2] + high[:2]) / 2) * scale + size / 2
        world = vertices[indices]
        normals = np.cross(world[:, 1] - world[:, 0], world[:, 2] - world[:, 0])
        lengths = np.linalg.norm(normals, axis=1)
        facing = np.abs(normals @ LIGHT) / np.maximum(lengths, 1e-12)
        shade = .66 + .29 * facing
        rgb = ((.18 + shade[:, None] * material) * 255).clip(0, 255).astype(np.uint8)
        for index, triangle in enumerate(screen[indices]):
            paint_triangle(rgba, depth, triangle, (*rgb[index], 255))

    return Image.fromarray(rgba).resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def write_thumbnail(path, mesh):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.thumbnail-', dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        render(mesh).save(temporary)
        temporary.replace(path)
