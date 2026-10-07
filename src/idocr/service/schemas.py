from pydantic import BaseModel


class OcrLineOut(BaseModel):
    text: str
    score: float
    box: list[list[float]]


class ImageMeta(BaseModel):
    width: int
    height: int
    scale: float
    exif_rotated: bool


class ModelMeta(BaseModel):
    det: str
    rec: str
    cls: str | None


class RawOcrResponse(BaseModel):
    request_id: str
    lines: list[OcrLineOut]
    image: ImageMeta
    model: ModelMeta
    elapsed_ms: int


class ErrorResponse(BaseModel):
    request_id: str | None
    error: str
