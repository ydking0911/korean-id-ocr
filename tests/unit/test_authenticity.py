import cv2
import numpy as np
import pytest

from idocr.core import authenticity as A
from idocr.core.result import DocumentType
from idocr.ocr.face import Face

RRN_BOX = [[100, 300], [500, 300], [500, 340], [100, 340]]  # 높이 40


def card_on_table(ratio: float, colorful: bool = True) -> np.ndarray:
    """회색 책상 위에 카드(또는 종이)를 놓은 이미지."""
    img = np.full((900, 1400, 3), 90, np.uint8)
    w = 900
    h = round(w / ratio)
    x0, y0 = 250, (900 - h) // 2
    card = np.full((h, w, 3), 245, np.uint8)
    if colorful:  # 분홍·하늘색 무늬
        xx = np.linspace(0, 6 * np.pi, w)[None, :]
        card[..., 2] = np.clip(225 + 25 * np.sin(xx), 0, 255).astype(np.uint8)
        card[..., 0] = np.clip(225 + 25 * np.cos(xx), 0, 255).astype(np.uint8)
    img[y0:y0 + h, x0:x0 + w] = card
    return img


def test_card_quad_and_ratio_on_table():
    img = card_on_table(A.CARD_RATIO)
    quad = A.find_card_quad(img)
    assert quad is not None
    ratio, method = A.card_ratio(img, quad, [])
    assert method == "contour" and ratio == pytest.approx(A.CARD_RATIO, rel=0.03)


def test_a4_sheet_flagged_by_aspect():
    c = A.run(card_on_table(1.414), DocumentType.RESIDENT_CARD, None, [], [])
    assert c.card_aspect["ok"] is False and "CARD_ASPECT" in c.reasons


def test_frame_ratio_reported_but_not_judged():
    img = np.full((720, 1280, 3), 230, np.uint8)  # 카드를 16:9로 잘라낸 사진
    c = A.run(img, DocumentType.RESIDENT_CARD, None, [[[0, 0], [1200, 0], [1200, 40], [0, 40]]], [])
    assert c.card_aspect["method"] == "frame" and c.card_aspect["ok"] is None
    assert "CARD_ASPECT" not in c.reasons and "CARD_EDGES_NOT_VISIBLE" in c.inconclusive


TEXT = [[[300, 250], [1000, 250], [1000, 290], [300, 290]], [[300, 600], [1000, 600], [1000, 640], [300, 640]]]


def test_plain_paper_flagged_colorful_card_not():
    assert "PLAIN_BACKGROUND" in A.run(card_on_table(A.CARD_RATIO, colorful=False),
                                       DocumentType.RESIDENT_CARD, None, TEXT, []).reasons
    assert "PLAIN_BACKGROUND" not in A.run(card_on_table(A.CARD_RATIO), DocumentType.RESIDENT_CARD, None, TEXT, []).reasons


def test_red_seal_does_not_make_paper_colorful():
    img = card_on_table(A.CARD_RATIO, colorful=False)
    cv2.circle(img, (900, 500), 60, (30, 30, 220), -1)  # 진한 빨간 직인
    assert "PLAIN_BACKGROUND" in A.run(img, DocumentType.RESIDENT_CARD, None, TEXT, []).reasons


@pytest.mark.parametrize("doc,face_x,ok", [
    (DocumentType.RESIDENT_CARD, 700, True),    # 주민등록증: 사진은 오른쪽
    (DocumentType.RESIDENT_CARD, 30, False),
    (DocumentType.DRIVER_LICENSE, 30, True),    # 운전면허증: 사진은 왼쪽
    (DocumentType.DRIVER_LICENSE, 700, False),
])
def test_face_must_be_on_photo_side(doc, face_x, ok):
    face = Face(face_x, 200, face_x + 60, 360, 0.95)  # 높이 160 = 주민번호 줄의 4배
    assert A._face_check([face], doc, RRN_BOX)["ok"] is ok


def test_tiny_face_is_not_the_id_photo():
    # 신형 주민등록증 좌하단 고스트 이미지처럼 작은 얼굴은 증명사진이 아니다
    face = Face(700, 200, 720, 225, 0.95)
    assert not A._face_check([face], DocumentType.RESIDENT_CARD, RRN_BOX)["ok"]


def test_no_rrn_skips_face_check():
    assert A._face_check([], DocumentType.RESIDENT_CARD, None) is None


def test_colorfulness_ignores_text_boxes():
    img = card_on_table(A.CARD_RATIO, colorful=False)
    cv2.putText(img, "TEXT", (400, 400), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 255), 8)
    box = [[380, 320], [700, 320], [700, 420], [380, 420]]
    assert A.colorfulness(img, A.find_card_quad(img), [box] + TEXT, []) < A.MIN_COLORFULNESS


def test_overexposed_background_is_inconclusive_not_suspicious():
    img = np.full((900, 1400, 3), 255, np.uint8)  # 하얗게 날아간 사진
    c = A.run(img, DocumentType.RESIDENT_CARD, None, TEXT, [])
    assert c.background["ok"] is None and "BACKGROUND_OVEREXPOSED" in c.inconclusive
    assert "PLAIN_BACKGROUND" not in c.reasons
