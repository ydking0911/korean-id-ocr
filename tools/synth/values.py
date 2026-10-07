"""정합성 있는 가짜 신분증 값 생성.

블로그(케이뱅크) 방식과 달리 값끼리 맞춘다: 주소의 시·군·구 ↔ 발급기관, 생년월일 ↔ 발급일,
면허번호 지역코드 ↔ 발급 경찰청, 적성검사 기간 ↔ 발급연도. 모든 값은 가짜다.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta

SURNAMES = [("김", "金", 21), ("이", "李", 15), ("박", "朴", 8), ("최", "崔", 5), ("정", "鄭", 5), ("강", "姜", 2),
            ("조", "趙", 2), ("윤", "尹", 2), ("장", "張", 2), ("임", "林", 2), ("한", "韓", 1), ("오", "吳", 1),
            ("서", "徐", 1), ("신", "申", 1), ("권", "權", 1), ("황", "黃", 1), ("안", "安", 1), ("송", "宋", 1),
            ("류", "柳", 1), ("홍", "洪", 1), ("남궁", "南宮", 0.2), ("제갈", "諸葛", 0.1)]
GIVEN = list("민서지수현우준영하은도윤예진성호재희동혁경태연유채아원석훈정빈소가나다라온결솔찬규")
HANJA = list("敏瑞智秀賢宇俊英夏恩道允藝珍成浩在熙東赫京泰然有采雅元錫勳正彬昭佳娜多羅溫潔率燦奎")

# 시·도 → [(시·군·구, 발급기관 접미)] (구: 구청장, 시: 시장, 군: 군수)
REGIONS = {
    "서울특별시": ["종로구", "중구", "용산구", "성동구", "마포구", "강남구", "송파구", "금천구", "관악구", "노원구"],
    "부산광역시": ["해운대구", "부산진구", "동래구", "사하구", "기장군"],
    "대구광역시": ["수성구", "달서구", "북구", "달성군"],
    "인천광역시": ["연수구", "남동구", "부평구", "강화군"],
    "광주광역시": ["서구", "북구", "광산구"],
    "대전광역시": ["유성구", "서구", "대덕구"],
    "울산광역시": ["남구", "중구", "울주군"],
    "세종특별자치시": [""],
    "경기도": ["수원시", "성남시", "고양시", "용인시", "부천시", "의정부시", "양평군", "가평군"],
    "강원특별자치도": ["춘천시", "원주시", "강릉시", "홍천군"],
    "충청북도": ["청주시", "충주시", "옥천군"],
    "충청남도": ["천안시", "아산시", "공주시", "태안군"],
    "전북특별자치도": ["전주시", "군산시", "익산시", "완주군"],
    "전라남도": ["목포시", "여수시", "순천시", "해남군"],
    "경상북도": ["포항시", "경주시", "구미시", "안동시", "울릉군"],
    "경상남도": ["창원시", "김해시", "진주시", "거제시", "남해군"],
    "제주특별자치도": ["제주시", "서귀포시"],
}
ROAD_STEMS = ["중앙", "평화", "세종", "가산디지털", "테헤란", "올림픽", "한강", "새마을", "대학", "시청", "역전", "공원",
              "번영", "희망", "동산", "문화", "구룡", "산업", "청계", "해안", "봉화", "충렬", "학교", "상공"]
BUILDINGS = ["대륭테크노타운", "현대아파트", "래미안", "푸르지오", "자이", "롯데캐슬", "한신아파트", "주공아파트",
             "벽산빌라", "센트럴파크", "그린빌", "하이츠"]

# 면허 발급 경찰청 → 면허번호 지역코드 (2021년 '지방' 명칭 삭제 전후 모두 지원)
POLICE = {"서울": "11", "부산": "12", "경기남부": "13", "강원": "14", "충북": "15", "충남": "16", "전북": "17",
          "전남": "18", "경북": "19", "경남": "20", "제주": "21", "대구": "22", "인천": "23", "광주": "24",
          "대전": "25", "울산": "26", "경기북부": "28"}
SIDO_TO_POLICE = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
                  "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "대전",
                  "경기도": None, "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남",
                  "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
                  "제주특별자치도": "제주"}
GYEONGGI_NORTH = {"고양시", "의정부시", "가평군"}

LICENSE_TYPES = [("1종보통", 45), ("2종보통", 35), ("1종대형", 8), ("2종원동기", 5), ("2종소형", 4),
                 ("1종특수(대형견인)", 1), ("1종특수(구난)", 1), ("1종소형", 1)]
SERIAL_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"


@dataclass
class Person:
    name: str
    name_hanja: str
    birth: date
    gender_digit: str
    rrn_back: str
    sido: str
    sigungu: str
    address_parts: list[str]  # 단어 단위 (렌더러가 줄바꿈)

    @property
    def rrn(self) -> str:
        return f"{self.birth:%y%m%d}-{self.gender_digit}{self.rrn_back}"


def _rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max(0, (end - start).days)))


def person(rng: random.Random, today: date, foreign_ratio: float = 0.0) -> Person:
    sur, sur_hanja, _ = rng.choices(SURNAMES, weights=[w for *_, w in SURNAMES])[0]
    n_given = rng.choices([1, 2, 3], weights=[8, 90, 2])[0]
    idx = [rng.randrange(len(GIVEN)) for _ in range(n_given)]
    birth = _rand_date(rng, date(1950, 1, 1), date(today.year - 18, 12, 31))
    male = rng.random() < 0.5
    if rng.random() < foreign_ratio:
        digit = ("5" if male else "6") if birth.year < 2000 else ("7" if male else "8")
    else:
        digit = ("1" if male else "2") if birth.year < 2000 else ("3" if male else "4")
    sido = rng.choice(list(REGIONS))
    sigungu = rng.choice(REGIONS[sido])
    road = f"{rng.choice(ROAD_STEMS)}{rng.choice(['로', '대로', '길'])}" + (
        f"{rng.randint(1, 40)}번길" if rng.random() < 0.3 else "")
    parts = [sido] + ([sigungu] if sigungu else []) + [road, str(rng.randint(1, 300))]
    if rng.random() < 0.6:
        parts.append(f"({rng.choice(BUILDINGS)}" + (f" {rng.randint(1, 30)}차)" if rng.random() < 0.3 else ")"))
    if rng.random() < 0.4:
        parts += [f"{rng.randint(101, 120)}동", f"{rng.randint(1, 25)}{rng.randint(1, 8):02d}호"]
    return Person(
        name=sur + "".join(GIVEN[i] for i in idx),
        name_hanja=sur_hanja + "".join(HANJA[i] for i in idx),
        birth=birth,
        gender_digit=digit,
        rrn_back=f"{rng.randint(0, 999999):06d}",
        sido=sido,
        sigungu=sigungu,
        address_parts=parts,
    )


def resident_issuer(p: Person) -> str:
    if not p.sigungu:
        return f"{p.sido}장"  # 세종특별자치시장
    suffix = {"구": "청장", "시": "장", "군": "수"}[p.sigungu[-1]]
    return f"{p.sido} {p.sigungu}{suffix}"


def resident_card(rng: random.Random, today: date) -> dict:
    p = person(rng, today)
    issue = _rand_date(rng, max(date(p.birth.year + 17, p.birth.month, 28), date(1999, 1, 1)), today)
    return {
        "document_type": "RESIDENT_CARD",
        "person": p,
        "fields": {
            "name": p.name,
            "name_hanja": p.name_hanja,
            "rrn": p.rrn,
            "issue_date": issue.isoformat(),
            "issuer": resident_issuer(p),
        },
        "render": {"issue_date": f"{issue:%Y.%m.%d}."},
    }


def driver_license(rng: random.Random, today: date) -> dict:
    p = person(rng, today, foreign_ratio=0.05)
    police = SIDO_TO_POLICE[p.sido] or ("경기북부" if p.sigungu in GYEONGGI_NORTH else "경기남부")
    first_year = rng.randint(max(p.birth.year + 18, 1985), today.year)
    issue = _rand_date(rng, date(first_year, 1, 1), today)
    issuer = f"{police}{'지방' if issue.year < 2021 else ''}경찰청장"
    number = f"{POLICE[police]}-{first_year % 100:02d}-{rng.randint(0, 999999):06d}-{rng.randint(10, 99):02d}"
    kinds = [rng.choices(LICENSE_TYPES, weights=[w for _, w in LICENSE_TYPES])[0][0]]
    if rng.random() < 0.12:
        extra = rng.choice([k for k, _ in LICENSE_TYPES if k != kinds[0]])
        kinds.append(extra)
    apt_year = issue.year + rng.choice([7, 9, 10])
    start, end = date(apt_year, 1, 1), date(apt_year, 12, 31)
    serial = "".join(rng.choice(SERIAL_CHARS) for _ in range(6))
    if not any(c.isdigit() for c in serial):
        serial = serial[:5] + str(rng.randint(0, 9))
    if not any(c.isalpha() for c in serial):
        serial = rng.choice("ABCDEFGHJK") + serial[1:]
    return {
        "document_type": "DRIVER_LICENSE",
        "person": p,
        "fields": {
            "license_number": number,
            "license_types": kinds,
            "name": p.name,
            "rrn": p.rrn,
            "aptitude_period": {"start": start.isoformat(), "end": end.isoformat(), "kind": "APTITUDE"},
            "issue_date": issue.isoformat(),
            "serial_code": serial,
            "issuer": issuer,
        },
        "render": {
            "license_types": " ".join(k[:2] + " " + k[2:] for k in kinds),
            "aptitude_start": f"{start:%Y.%m.%d}.",
            "aptitude_end": f"~ {end:%Y.%m.%d}.",
            "issue_date": f"{issue:%Y}. {issue:%m}. {issue:%d}.",
        },
    }
