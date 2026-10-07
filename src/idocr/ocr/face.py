"""얼굴 검출 (OpenCV YuNet, CPU). 위조 의심 신호에서 '사진 영역에 얼굴이 있는가'에만 쓴다."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_MAX_SIDE = 960  # 검출 입력 크기 상한 (속도)


@dataclass(frozen=True)
class Face:
    x0: float
    y0: float
    x1: float
    y1: float
    score: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


class FaceDetector:
    def __init__(self, model_path: Path, score_threshold: float = 0.6):
        if not Path(model_path).exists():
            raise FileNotFoundError(str(model_path))
        # 엔진(스레드)마다 하나. 입력 크기만 요청마다 바꾼다
        self._det = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold)

    def detect(self, bgr: np.ndarray) -> list[Face]:
        h, w = bgr.shape[:2]
        s = min(1.0, _MAX_SIDE / max(h, w))
        img = cv2.resize(bgr, (max(1, round(w * s)), max(1, round(h * s)))) if s < 1.0 else bgr
        self._det.setInputSize((img.shape[1], img.shape[0]))
        _, found = self._det.detect(img)
        if found is None:
            return []
        return [Face(float(f[0]) / s, float(f[1]) / s, float(f[0] + f[2]) / s, float(f[1] + f[3]) / s, float(f[-1]))
                for f in found]
