from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rawpy
from PIL import Image, ImageOps


@dataclass(frozen=True)
class AdjustmentParams:
    exposure: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    temperature: float = 0.0


class ImageEngine:
    RAW_EXTENSIONS = {
        ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
        ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw", ".raw",
    }
    REGULAR_EXTENSIONS = {".jpg", ".jpeg", ".png"}

    def __init__(self, preview_max_side: int = 1400):
        if preview_max_side <= 0:
            raise ValueError("预览图最长边必须大于 0")
        self.preview_max_side = preview_max_side
        self.original_image: np.ndarray | None = None
        self.preview_image: np.ndarray | None = None

    @property
    def has_image(self) -> bool:
        return self.original_image is not None and self.preview_image is not None

    def load_image(self, file_path: str | Path) -> np.ndarray:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")

        suffix = path.suffix.lower()
        if suffix in self.RAW_EXTENSIONS:
            image = self._read_raw(path)
        elif suffix in self.REGULAR_EXTENSIONS:
            image = self._read_regular_image(path)
        else:
            raise ValueError(f"不支持的图片格式：{suffix or '无扩展名'}")

        image = self._as_rgb_uint8(image)
        preview = self._create_preview(image)

        # 加载成功后再替换旧图，避免读取失败时破坏当前工作状态。
        self.original_image = image
        self.preview_image = preview
        return image

    def render_preview(self, params: AdjustmentParams) -> np.ndarray:
        if self.preview_image is None:
            raise RuntimeError("请先导入图片")
        return self.apply_adjustments(self.preview_image, params)

    def render_full_resolution(self, params: AdjustmentParams) -> np.ndarray:
        if self.original_image is None:
            raise RuntimeError("请先导入图片")
        return self.apply_adjustments(self.original_image, params)

    @classmethod
    def apply_adjustments(
        cls, image: np.ndarray, params: AdjustmentParams
    ) -> np.ndarray:
        cls._validate_rgb_array(image)

        # 统一在 float32 中计算，减少连续调整造成的精度损失。
        result = image.astype(np.float32)
        if params.exposure != 0:
            result = cls.adjust_exposure(result, params.exposure)
        if params.contrast != 0:
            result = cls.adjust_contrast(result, params.contrast)
        if params.temperature != 0:
            result = cls.adjust_temperature(result, params.temperature)
        if params.saturation != 0:
            result = cls.adjust_saturation(result, params.saturation)

        return np.clip(np.rint(result), 0, 255).astype(np.uint8)

    @staticmethod
    def adjust_exposure(image: np.ndarray, value: float) -> np.ndarray:
        # -100～100 映射为 -2～+2 EV，0 表示不调整。
        factor = 2.0 ** (value / 50.0)
        result = image.astype(np.float32, copy=False) * factor
        return np.clip(result, 0, 255)

    @staticmethod
    def adjust_contrast(image: np.ndarray, value: float) -> np.ndarray:
        # 以 128 为锚点拉伸或压缩像素，避免改变整体中灰位置。
        factor = 1.0 + value / 100.0
        result = (image.astype(np.float32, copy=False) - 128.0) * factor + 128.0
        return np.clip(result, 0, 255)

    @staticmethod
    def adjust_saturation(image: np.ndarray, value: float) -> np.ndarray:
        # OpenCV 的 float32 HSV 使用 RGB 0～1、S 0～1 的数值范围。
        rgb = np.clip(image, 0, 255).astype(np.float32, copy=False) / 255.0
        rgb = np.ascontiguousarray(rgb)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        factor = 1.0 + value / 100.0
        hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0.0, 1.0)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * 255.0
        return np.clip(result, 0, 255)

    @staticmethod
    def adjust_temperature(image: np.ndarray, value: float) -> np.ndarray:
        # 正值增加红色并减少蓝色（暖色），负值反之（冷色）。
        result = image.astype(np.float32, copy=True)
        red_scale = 1.0 + value / 200.0
        blue_scale = 1.0 - value / 200.0
        result[..., 0] *= red_scale
        result[..., 2] *= blue_scale
        return np.clip(result, 0, 255)

    @staticmethod
    def save_jpeg(
        image: np.ndarray, file_path: str | Path, quality: int = 95
    ) -> None:
        ImageEngine._validate_rgb_array(image)
        if image.dtype != np.uint8:
            raise TypeError("保存 JPG 前必须将图像转换为 uint8")
        if not 1 <= quality <= 100:
            raise ValueError("JPG 质量必须在 1～100 之间")

        path = Path(file_path)
        if not path.parent.is_dir():
            raise FileNotFoundError(f"保存目录不存在：{path.parent}")

        # subsampling=0 关闭色度抽样，尽量保留边缘和色彩细节。
        output = Image.fromarray(np.ascontiguousarray(image))
        output.save(
            str(path),
            format="JPEG",
            quality=quality,
            subsampling=0,
            optimize=True,
        )

    @staticmethod
    def _read_regular_image(path: Path) -> np.ndarray:
        with Image.open(path) as source:
            # 按 EXIF 方向旋转，确保手机照片在软件中方向正确。
            oriented = ImageOps.exif_transpose(source)
            rgb = oriented.convert("RGB")
            return np.array(rgb, dtype=np.uint8, copy=True)

    @staticmethod
    def _read_raw(path: Path) -> np.ndarray:
        # RAW 解码只发生一次；后续预览和导出都复用解码后的 RGB 原图。
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        return np.ascontiguousarray(rgb, dtype=np.uint8)

    def _create_preview(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        scale = min(1.0, self.preview_max_side / max(height, width))
        if scale == 1.0:
            return image.copy()

        new_width = max(1, round(width * scale))
        new_height = max(1, round(height * scale))
        return cv2.resize(
            image,
            (new_width, new_height),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _as_rgb_uint8(image: np.ndarray) -> np.ndarray:
        ImageEngine._validate_rgb_array(image)
        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)
        return np.ascontiguousarray(image)

    @staticmethod
    def _validate_rgb_array(image: np.ndarray) -> None:
        if not isinstance(image, np.ndarray):
            raise TypeError("图像必须是 NumPy 数组")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("图像必须是 H×W×3 的 RGB 数组")
        if image.shape[0] == 0 or image.shape[1] == 0:
            raise ValueError("图像尺寸不能为空")
