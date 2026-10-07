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
5. **PP-OCRv6 인식 모델은 한국어 미지원** (중·영·일·라틴 계열 50개 언어). v6는 검출기만 비교 후보로 둔다 (2절).

## 2. 모델 파일 (✅ 확인 완료, 2026-10-07)

### 확인 결과 (개발 PC에서 확인)

| 항목 | 결과 |
|---|---|
| `monkt/paddleocr-onnx` | 존재. `detection/v5/det.onnx`(84MB), `languages/korean/rec.onnx`(13MB), `languages/korean/dict.txt` 경로 그대로 |
| `PaddlePaddle/korean_PP-OCRv5_mobile_rec`, `PP-OCRv5_server_det`, `PP-OCRv5_mobile_det` | 모두 존재 (Paddle 형식 원본) |
| RapidOCR 공식 URL | `rapidocr` 3.9.2 휠의 `default_models.yaml`과 일치 |
| monkt `det.onnx` | README에 server/mobile 구분 없음. 크기(84MB)로 보아 **server 모델로 판단** |

PaddleOCR 공식 모델 목록 기준 검출 모델 비교:

| 검출 모델 | 크기 | 정확도(Hmean) | CPU 추론 |
|---|---|---|---|
| PP-OCRv5_server_det | 101MB | 83.8% | 383ms |
| PP-OCRv5_mobile_det | 4.7MB | 79.0% | 58ms |

신분증은 글자가 크고 반듯한 인쇄체라 mobile 검출로도 정확도 손실이 작을 것으로 보고, CPU에서 6~7배 빠른 mobile을 기본으로 한다.

### ✅ 기본 모델 조합: 출처를 RapidOCR 공식 배포 하나로 통일

| 용도 | 모델 | SHA256 |
|---|---|---|
| 검출 | `ch_PP-OCRv5_det_mobile.onnx` ("ch"지만 v5 검출기는 다국어 공용) | `4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae` |
| 인식 | `korean_PP-OCRv5_rec_mobile.onnx` | `cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b` |
| 사전 | `ppocrv5_korean_dict.txt` | (yaml에 해시 없음 → 받은 뒤 직접 기록) |
| 방향 분류 | `ch_ppocr_mobile_v2.0_cls_mobile.onnx` (rapidocr Cls 기본값, 0°/180°) | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

URL 접두사: `https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/`
- `onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx`
- `onnx/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx`
- `paddle/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile/ppocrv5_korean_dict.txt`
- `onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx`

모델은 **Docker 이미지 빌드 시점에 받아 SHA256 검증** 후 포함한다. 런타임 다운로드 없음.
(modelscope가 빌드 환경에서 막히면 개발 PC에서 받아 `models/`에 두고 COPY.)

### 비교 후보 (평가 하네스에서 측정)

| 조합 | 목적 |
|---|---|
| v5 mobile det + v5 korean rec | **기본** |
| v5 server det + v5 korean rec | 정확도 상한 확인 |
| **v6 det small + v5 korean rec** | v6 검출기가 v5보다 정확하다고 함. `multi_PP-OCRv6_det_small` SHA256 `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| monkt det(server) + monkt korean rec | monkt 모델은 비교용으로만 보관 |

### ⚠️ 초기화 시 반드시 모델을 명시

rapidocr 3.9.2 기본값은 `ocr_version: PP-OCRv6`, `lang_type: ch`인데 **PP-OCRv6 인식 모델은 한국어를 지원하지 않는다**
(중·영·일·라틴 계열 50개 언어). 옵션 없이 `RapidOCR()`만 호출하면 한글이 제대로 인식되지 않는다.
→ `engine.py`에서 Det/Rec/Cls `model_path`를 **항상 명시**하고, 기동 시 한글 샘플 문자열 인식 self-test로 잘못된 모델 로드를 막는다.

## 3. 기타 라이브러리 버전

| 패키지 | 최신 |
|---|---|
| `discord.py` | 2.7.1 |
| `onnxruntime` | 1.30.0 |
