# syntax=docker/dockerfile:1
# CPU 전용 OCR worker. 모델은 빌드 전에 호스트에서 받아 둔다:
#   python scripts/download_models.py && docker compose build

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

# 의존성 레이어를 소스와 분리해 캐시
COPY pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install -r /tmp/req.txt \
 # rapidocr가 끌어오는 opencv-python(GUI 포함)을 headless로 교체 → libGL 등 OS 패키지 불필요
 && CV_VER=$(python -c "import importlib.metadata as m; print(m.version('opencv-python'))") \
 && pip uninstall -y opencv-python \
 && pip install "opencv-python-headless==${CV_VER}"
COPY src ./src
RUN pip install --no-deps . \
 # rapidocr 휠에 동봉된 기본 모델(PP-OCRv6, 한국어 미지원) 제거 → 잘못된 모델이 로드될 여지를 없앰
 && rm -f /opt/venv/lib/python*/site-packages/rapidocr/models/*.onnx


FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home idocr

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IDOCR_MODEL_DIR=/app/models

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY scripts/download_models.py ./scripts/
COPY models ./models

# 모델 파일 존재·SHA256 검증. 다른 모델로 배선만 시험할 때만 VERIFY_MODELS=0
ARG VERIFY_MODELS=1
RUN if [ "$VERIFY_MODELS" = "1" ]; then python scripts/download_models.py --verify-only; fi

USER idocr
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "--factory", "idocr.service.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
