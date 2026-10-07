# 01. 기술 조사 결과 (2026-10-07 기준)

## 1. RapidOCR 패키지/API

| 항목 | 확인 결과 |
|---|---|
| 현재 패키지 | `rapidocr` **3.9.2** (최신) |
| 구버전 패키지 | `rapidocr_onnxruntime` 1.2.3 — 더 이상 기능 추가 없음, 사용하지 않음 |
| 추론 엔진 | `onnxruntime`은 **의존성에 포함되지 않음** → 별도 설치 필요 (`onnxruntime` 1.30.0, CPU 빌드) |
| 주요 의존성 | opencv-python, numpy, pyclipper, shapely, Pillow, omegaconf, PyYAML, requests 등. **PyTorch/Paddle 불필요** |
| 입력 타입 | `str | Path | np.ndarray | bytes | PIL.Image` — **bytes 직접 입력 가능** → 디스크 쓰기 불필요 |
| 출력 타입 | `RapidOCROutput` 객체 (`.txts`, `.scores`, `.boxes`, `.elapse`). 구버전의 `(result, elapsed)` 튜플 아님 |

### 새 API 사용 형태 (3.x)

생성자 인자가 바뀌어서 `det_model_path=` 같은 키워드는 쓰지 않고, `params` 딕셔너리에 `섹션.키` 형식으로 넘긴다.

```python
from rapidocr import RapidOCR

ocr = RapidOCR(params={
    "Global.log_level": "error",          # 기본 info → 낮춰야 함 (아래 참고)
    "Det.model_path": "models/det.onnx",
    "Rec.model_path": "models/korean_rec.onnx",
    "Rec.rec_keys_path": "models/korean_dict.txt",
    "Global.use_cls": True,               # 180도 뒤집힌 텍스트 보정
    "Cls.model_path": "models/cls.onnx",  # 지정 안 하면 첫 실행 때 자동 다운로드 시도
    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
})

out = ocr(image_bytes)        # bytes 그대로
texts = out.txts or ()        # tuple[str] | None
scores = out.scores or ()
```

### 설계에 영향을 주는 세부 사항

1. **기본 설정이 PP-OCRv6(multi)로 바뀌었다.** `config.yaml` 기본값이 `ocr_version: PP-OCRv6`, `lang_type: ch`다.
   모델 경로를 명시하지 않으면 우리가 의도한 PP-OCRv5 한국어 모델이 아닌 다른 모델이 로드된다 → **경로를 항상 명시**한다.
2. **Cls(방향 분류) 모델은 `use_cls=False`여도 생성자에서 로드된다.** 경로를 주지 않으면 modelscope.cn에서 다운로드를 시도한다.
   운영 서버의 외부 접근을 막을 거라면 cls 모델도 로컬에 두고 경로를 지정해야 한다.
3. **dict 처리**: RapidAI가 배포하는 ONNX는 문자 사전을 모델 메타데이터에 내장한다. 내장 사전이 없는 ONNX(예: monkt 변환본일 가능성)는
   `Rec.rec_keys_path`가 반드시 필요하다. 둘 다 없으면 초기화 에러.
4. **로깅**: rapidocr 내부 로거는 기본 `info` 레벨이고 `logger.warning(e)`로 예외를 그대로 찍는 곳이 있다.
   현재 코드상 OCR 텍스트를 직접 로그하지는 않지만, 방어적으로 `Global.log_level=error` + 우리 쪽 로깅 필터를 둔다.
5. **`rapidocr`의 PP-OCRv6 multi rec 모델**이 새로 생겼다. 한국어 지원 여부와 정확도는 미확인 → 벤치마크 후보로만 둔다.

## 2. 모델 파일

### `monkt/paddleocr-onnx` (Hugging Face)

**이 작업 환경에서는 huggingface.co 접근이 네트워크 정책으로 차단되어(403) 파일 목록을 직접 확인하지 못했다.**
개발 PC에서 아래를 확인해야 한다.

- [ ] `detection/v5/det.onnx`, `languages/korean/rec.onnx`, `languages/korean/dict.txt` 경로가 실제로 존재하는지
- [ ] `det.onnx` 약 84MB → 크기상 PP-OCRv5 **server** det일 가능성이 높음 (mobile det는 수 MB). CPU 지연시간에 큰 영향
- [ ] rec.onnx에 문자 사전이 내장되어 있는지 (없으면 dict.txt 필수)
- [ ] 라이선스(Apache 2.0) 및 원본 Paddle 모델 버전 명시 여부
- [ ] 파일 SHA256을 기록해 다운로드 스크립트에서 검증

확인 명령 예시 (개발 PC):

```bash
pip install huggingface_hub
python -c "from huggingface_hub import list_repo_files as f; print('\n'.join(f('monkt/paddleocr-onnx')))"
```

### 대안: RapidOCR 공식 배포 모델 (modelscope)

`rapidocr` 3.9.2의 `default_models.yaml`에 한국어 모델이 공식 등록되어 있다. 출처가 RapidOCR 본가라 API 호환성이 보장된다.

| 용도 | 모델 키 | SHA256 (앞 16자) |
|---|---|---|
| 인식 (ONNX) | `korean_PP-OCRv5_rec_mobile` | `cd6e2ea50f6943ca` |
| 인식 (ONNX, 구버전) | `korean_PP-OCRv4_rec_mobile` | `ab151ba9065eccd9` |
| 검출 | `ch_PP-OCRv5_det_mobile` / `ch_PP-OCRv5_det_server` | (yaml 참조) |

URL 형식: `https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx`

**제안**: Phase 0 벤치마크에서 `monkt` 모델과 RapidAI 공식 모델을 같은 샘플로 비교하고, 정확도가 비슷하면
API 호환성·해시 검증이 쉬운 공식 모델을 쓴다. 검출 모델은 mobile/server 둘 다 측정한다.

## 3. 기타 라이브러리 버전

| 패키지 | 최신 |
|---|---|
| `discord.py` | 2.7.1 |
| `onnxruntime` | 1.30.0 |
