"""生成透明素材、眨眼帧和以月亮顶点为锚点的摆动动画。

默认源图：assets/source/columbina_source.jpg

脚本优先使用 rembg 的 isnet-anime 模型移除棋盘背景。分割时关闭 alpha
matting，且不对角色或蒙版使用高斯模糊，从而尽量保持头发细节清晰。
"""

from __future__ import annotations

import argparse
import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DEFAULT_SOURCE = ASSETS_DIR / "source" / "columbina_source.jpg"
CANVAS_SIZE = (560, 520)

# 坐标使用源图宽高比例，分别表示月亮顶点和两只眼睛中心。
MOON_PIVOT_NORMALIZED = (0.515, 0.045)
LEFT_EYE_NORMALIZED = (0.455, 0.385)
RIGHT_EYE_NORMALIZED = (0.548, 0.385)


def remove_checkerboard_fallback(image: Image.Image) -> Image.Image:
    """无 rembg 时，只删除从四边连通的浅灰棋盘像素。"""

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    background = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def is_checker_pixel(x: int, y: int) -> bool:
        red, green, blue = pixels[x, y]
        spread = max(red, green, blue) - min(red, green, blue)
        return min(red, green, blue) >= 222 and spread <= 13

    def add(x: int, y: int) -> None:
        index = y * width + x
        if not background[index] and is_checker_pixel(x, y):
            background[index] = 1
            queue.append((x, y))

    for x in range(width):
        add(x, 0)
        add(x, height - 1)
    for y in range(height):
        add(0, y)
        add(width - 1, y)

    while queue:
        x, y = queue.popleft()
        if x:
            add(x - 1, y)
        if x + 1 < width:
            add(x + 1, y)
        if y:
            add(x, y - 1)
        if y + 1 < height:
            add(x, y + 1)

    alpha = Image.new("L", (width, height), 255)
    alpha.putdata(bytes(0 if value else 255 for value in background))
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def remove_background(image: Image.Image) -> Image.Image:
    """优先使用动漫分割模型抠图，不做发丝羽化或模糊。"""

    try:
        from rembg import new_session, remove
    except ImportError:
        print("未安装 rembg，使用无模糊棋盘背景备用算法。")
        return remove_checkerboard_fallback(image)

    result = remove(
        image.convert("RGB"),
        session=new_session("isnet-anime"),
        alpha_matting=False,
        post_process_mask=False,
    ).convert("RGBA")

    # 仅清除几乎全透明的模型噪点，不使用 GaussianBlur。
    alpha = result.getchannel("A").point(lambda value: 0 if value < 8 else value)
    result.putalpha(alpha)
    return result


def make_blink_frame(character: Image.Image) -> Image.Image:
    """只修改眼睛区域生成闭眼帧，头发和服饰像素保持不变。"""

    blink = character.copy()
    draw = ImageDraw.Draw(blink, "RGBA")
    width, height = blink.size
    eye_width = max(10, round(width * 0.034))
    eye_height = max(7, round(height * 0.023))
    skin = (251, 245, 247, 255)
    eyelash = (72, 43, 83, 255)

    for center_x_ratio, center_y_ratio in (
        LEFT_EYE_NORMALIZED,
        RIGHT_EYE_NORMALIZED,
    ):
        center_x = round(width * center_x_ratio)
        center_y = round(height * center_y_ratio)
        box = (
            center_x - eye_width,
            center_y - eye_height,
            center_x + eye_width,
            center_y + eye_height,
        )
        draw.ellipse(box, fill=skin)
        line_y = center_y + round(eye_height * 0.08)
        points = [
            (center_x - eye_width + 3, line_y - 1),
            (center_x, line_y + round(eye_height * 0.35)),
            (center_x + eye_width - 3, line_y - 1),
        ]
        draw.line(
            points,
            fill=eyelash,
            width=max(3, round(width * 0.004)),
            joint="curve",
        )

    blink.putalpha(character.getchannel("A"))
    return blink


def fit_character(character: Image.Image) -> tuple[Image.Image, tuple[float, float]]:
    """缩放角色并返回缩放后的月亮锚点坐标。"""

    scale = min(430 / character.width, 430 / character.height)
    size = (
        max(1, round(character.width * scale)),
        max(1, round(character.height * scale)),
    )
    resized = character.resize(size, Image.Resampling.LANCZOS)
    pivot = (
        size[0] * MOON_PIVOT_NORMALIZED[0],
        size[1] * MOON_PIVOT_NORMALIZED[1],
    )
    return resized, pivot


def compose_pivot_frame(
    character: Image.Image,
    pivot_in_character: tuple[float, float],
    *,
    angle: float,
    y_offset: int = 0,
) -> Image.Image:
    """让整体绕月亮顶点旋转，同时保持顶点的屏幕坐标不动。"""

    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    fixed_pivot = (CANVAS_SIZE[0] // 2, 24)
    x = round(fixed_pivot[0] - pivot_in_character[0])
    y = round(fixed_pivot[1] - pivot_in_character[1] + y_offset)
    canvas.alpha_composite(character, (x, y))
    return canvas.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        center=fixed_pivot,
        expand=False,
    )


def rgba_to_gif_frame(frame: Image.Image) -> Image.Image:
    """转换为带固定透明色索引的 GIF 调色板帧。"""

    alpha = frame.getchannel("A")
    palette_frame = frame.convert("RGB").quantize(
        colors=255, method=Image.Quantize.MEDIANCUT
    )
    palette = palette_frame.getpalette()
    palette.extend([0] * (768 - len(palette)))
    palette[765:768] = [0, 0, 0]
    palette_frame.putpalette(palette)
    transparent_mask = alpha.point(lambda value: 255 if value <= 12 else 0)
    palette_frame.paste(255, mask=transparent_mask)
    palette_frame.info["transparency"] = 255
    palette_frame.info["disposal"] = 2
    return palette_frame


def save_gif(path: Path, frames: list[Image.Image], duration: int) -> None:
    gif_frames = [rgba_to_gif_frame(frame) for frame in frames]
    gif_frames[0].save(
        path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=duration,
        loop=0,
        transparency=255,
        disposal=2,
        optimize=False,
    )


def build_animations(character: Image.Image) -> None:
    """生成眨眼、行走和点击动画。"""

    blink_character = make_blink_frame(character)
    open_fitted, pivot = fit_character(character)
    blink_fitted, _ = fit_character(blink_character)

    idle_frames = []
    for index in range(32):
        phase = 2 * math.pi * index / 32
        current = blink_fitted if index in (15, 16, 17) else open_fitted
        idle_frames.append(
            compose_pivot_frame(current, pivot, angle=10.0 * math.sin(phase))
        )

    walk_frames = []
    for index in range(24):
        phase = 2 * math.pi * index / 24
        current = blink_fitted if index in (11, 12) else open_fitted
        walk_frames.append(
            compose_pivot_frame(
                current,
                pivot,
                angle=9.0 * math.sin(phase),
                y_offset=-abs(round(3 * math.sin(phase * 2))),
            )
        )

    action_frames = []
    for index in range(18):
        phase = 2 * math.pi * index / 18
        current = blink_fitted if index in (7, 8, 9) else open_fitted
        action_frames.append(
            compose_pivot_frame(current, pivot, angle=10.5 * math.sin(phase * 2))
        )

    save_gif(ASSETS_DIR / "idle.gif", idle_frames, duration=80)
    save_gif(ASSETS_DIR / "walk.gif", walk_frames, duration=75)
    save_gif(ASSETS_DIR / "action.gif", action_frames, duration=70)

    static_frame = compose_pivot_frame(open_fitted, pivot, angle=0)
    static_frame.save(ASSETS_DIR / "columbina.png")
    tray = static_frame.copy()
    tray.thumbnail((128, 128), Image.Resampling.LANCZOS)
    tray_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    tray_canvas.alpha_composite(
        tray, ((128 - tray.width) // 2, (128 - tray.height) // 2)
    )
    ImageEnhance.Contrast(tray_canvas).enhance(1.08).save(
        ASSETS_DIR / "tray_icon.png"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成哥伦比娅桌宠透明动画")
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"源 JPG/PNG，默认：{DEFAULT_SOURCE}",
    )
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"没有找到源图：{source}")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    character = remove_background(Image.open(source))
    build_animations(character)
    print(f"清晰眨眼与月亮锚点摆动素材已生成到：{ASSETS_DIR}")


if __name__ == "__main__":
    main()

