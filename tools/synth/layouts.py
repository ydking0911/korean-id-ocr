"""견본 이미지 기준 필드 배치. 좌표는 samples/specimen의 견본(주민등록증 1573x1000, 면허증 1581x995)을
한국어 모델로 인식한 박스(docs/02-architecture.md 4.5절)에서 잡았다.

- mask: 템플릿을 만들 때 지울 영역 (x0, y0, x1, y1)
- slots: 새 값을 그릴 위치. (x, 줄 중심 y, 글자 크기 px, 정렬, 최대 오른쪽 x)
- seals: 직인 영역. 붉은 픽셀만 떼어 두었다가 글자를 그린 뒤 다시 얹는다
- keep: 지우지 않는 고정 라벨 (제목, '적성검사', '기 간 :')
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Slot:
    x: int
    cy: int
    size: int
    align: str = "left"  # left | center
    max_x: int | None = None


@dataclass(frozen=True)
class Layout:
    name: str
    specimen: str
    size: tuple[int, int]
    masks: dict[str, tuple[int, int, int, int]]
    slots: dict[str, Slot | list[Slot]]
    seals: list[tuple[int, int, int, int]] = field(default_factory=list)


RESIDENT = Layout(
    name="resident_card",
    specimen="resident_card.webp",
    size=(1573, 1000),
    masks={
        "name": (140, 238, 800, 362),
        "rrn": (135, 378, 790, 468),
        "address": (105, 490, 985, 652),
        "issue_date": (500, 735, 910, 815),
        "issuer": (295, 795, 1335, 914),
    },
    slots={
        "name": Slot(152, 300, 74),
        "rrn": Slot(148, 423, 70),
        "address": [Slot(116, 538, 50, max_x=975), Slot(118, 606, 50, max_x=975)],
        "issue_date": Slot(703, 776, 50, align="center"),
        "issuer": Slot(712, 855, 62, align="center"),
    },
    seals=[(1100, 700, 1330, 925)],
)

LICENSE = Layout(
    name="driver_license",
    specimen="driver_license.webp",
    size=(1581, 995),
    masks={
        "license_types": (76, 28, 310, 120),
        "license_number": (595, 148, 1345, 252),
        "name": (598, 255, 1010, 348),
        "rrn": (598, 332, 1165, 414),
        "address": (595, 405, 1300, 612),
        "aptitude_start": (826, 606, 1172, 677),
        "aptitude_end": (868, 676, 1248, 742),
        "serial_code": (1306, 722, 1492, 782),
        "issue_row": (592, 828, 1538, 930),
    },
    slots={
        "license_types": Slot(88, 74, 50),
        "license_number": Slot(607, 200, 82),
        "name": Slot(607, 302, 62),
        "rrn": Slot(609, 373, 62),
        "address": [Slot(610, 445, 47, max_x=1295), Slot(610, 511, 47, max_x=1295), Slot(610, 576, 47, max_x=1295)],
        "aptitude_start": Slot(850, 641, 50),
        "aptitude_end": Slot(878, 708, 50),
        "serial_code": Slot(1319, 752, 38),
        "issue_date": Slot(604, 880, 44),
        "issuer": Slot(918, 878, 62),
    },
    seals=[(1350, 760, 1532, 942)],
)

LAYOUTS = {"RESIDENT_CARD": RESIDENT, "DRIVER_LICENSE": LICENSE}
