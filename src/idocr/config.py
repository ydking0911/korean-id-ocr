from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 `IDOCR_*`로 설정한다. 예: IDOCR_OCR_WORKERS=2"""

    model_config = SettingsConfigDict(env_prefix="IDOCR_", env_file=".env", extra="ignore")

    # 모델 파일 (model_dir 기준 상대 경로). 기본 조합은 docs/01-research.md 2절
    model_dir: Path = Path("models")
    det_model: str = "ch_PP-OCRv5_det_mobile.onnx"
    rec_model: str = "korean_PP-OCRv5_rec_mobile.onnx"
    rec_keys: str = "ppocrv5_korean_dict.txt"
    cls_model: str = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
    # 줄 단위 방향 분류(0°/180°). 짧은 줄(이름 등)을 뒤집힌 것으로 오판해 기본으로 끈다.
    # 뒤집힌 사진은 파이프라인의 180° 재시도 패스가 처리한다 (docs/09-roadmap.md 4단계 기록)
    use_cls: bool = False

    # 동시성: ocr_workers × ort_intra_threads ≤ 코어 수 권장
    ocr_workers: int = 2
    ort_intra_threads: int = 3
    queue_limit: int = 16
    request_timeout_s: float = 30.0

    # 입력 제한
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_side_len: int = 2000

    # /v1/ocr/raw는 원문(주민번호 전체 포함)을 돌려주므로 운영에서는 끈다
    enable_raw_endpoint: bool = False

    # 기동 시 인식 모델 문자 집합에 한글이 있는지 확인. 비한국어 모델로 배선만 시험할 때만 끈다
    require_hangul: bool = True

    # 주민번호 출력: full(개발 기본) | masked("900101-1******")
    rrn_output: Literal["full", "masked"] = "full"

    # 필드 채택 신뢰도 임계값 (docs/05-output-schema.md 6절). 평가 하네스로 재조정 예정
    threshold_numeric: float = 0.90
    threshold_text: float = 0.85
    threshold_address: float = 0.80

    log_level: str = "INFO"

    def model_path(self, name: str) -> Path:
        return self.model_dir / name


@lru_cache
def get_settings() -> Settings:
    return Settings()
