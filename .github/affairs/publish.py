# -*- coding: utf-8 -*-
"""그날의 시사 용어를 앱이 받는 달 파일(affairs/YYYY-MM.json)에 넣는다 — GitHub Actions(affairs.yml)가 매일 아침 부른다.

원본: 뉴스 브리핑 저장소(공개)의 App Terms 작업 결과
    https://raw.githubusercontent.com/allenst486de/news_briefing_system/main/data/app_terms/YYYY/MM-DD.json
    {"date": "...", "terms": [{"term", "reading", "meaning", "category", "categoryName", "url", ...}, ...]}
고르는 규칙(앞에서부터 다섯 개까지):
    · 표제·뜻풀이·분야·위키백과 주소가 있는 것
    · 금칙어가 없는 것 — 목록은 해시(banned.json)로만 둔다(원문은 앱 소스에만)
    · 최근 12개월 안에 앱에 실렸거나(bundled.json) 이미 올린 용어가 아닌 것
오늘(KST)보다 뒤 날짜는 올리지 않는다. 이미 다섯 개가 있으면 그대로 둔다(한 번 연 용어가 바뀌지 않게).
날짜를 안 주면 오늘과 지난 이틀 중 빈 날을 채운다(예약 실행이 늦거나 빠진 날 보충).

    python .github/affairs/publish.py                 # 오늘(KST) + 지난 이틀 중 빈 날
    python .github/affairs/publish.py --date 2026-09-24
    python .github/affairs/publish.py --source 파일.json --date 2026-09-24   # 원본을 파일로(시험용)
"""
import argparse
import hashlib
import json
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent            # docs 저장소 뿌리 = 사이트 뿌리
OUT = ROOT / "affairs"
KST = timezone(timedelta(hours=9))
PER_DAY = 5
# 받기 기능을 넣은 날(2026-09-23)까지는 앱에 실린 9월호 용어가 이미 열렸다 — 그 뒤 날짜부터 올린다.
# 9/24~9/30 은 앱에 미리 쓴 용어가 있지만 받은 용어(그날 실제 뉴스)가 같은 날짜를 덮는다
FIRST_DAY = date(2026, 9, 24)
# 날짜를 안 주고 돌리면 오늘과 지난 이틀까지 빈 날을 채운다
BACKFILL_DAYS = 2
SOURCE = "https://raw.githubusercontent.com/allenst486de/news_briefing_system/main/data/app_terms/{y}/{md}.json"

BANNED = json.loads((HERE / "banned.json").read_text(encoding="utf-8"))
HASHES = set(BANNED["hashes"])
BUNDLED = json.loads((HERE / "bundled.json").read_text(encoding="utf-8"))


def banned(text):
    text = unicodedata.normalize("NFC", text)
    for safe in BANNED["safe"]:
        text = text.replace(safe, "")
    for length in BANNED["lengths"]:
        for start in range(0, len(text) - length + 1):
            if hashlib.sha256(text[start:start + length].encode()).hexdigest() in HASHES:
                return True
    return False


def earlier_terms(day):
    """day 이전 12개월 안에 실렸거나 올린 용어"""
    cutoff = day - timedelta(days=366)
    seen = set()
    for key, terms in BUNDLED.items():
        if cutoff <= date.fromisoformat(key) < day:
            seen.update(terms)
    for path in OUT.glob("*.json"):
        for key, terms in json.loads(path.read_text(encoding="utf-8"))["days"].items():
            if cutoff <= date.fromisoformat(key) < day:
                seen.update(t["term"] for t in terms)
    return seen


def pick(raw, day):
    seen = earlier_terms(day)
    chosen, skipped = [], []
    for t in raw:
        term, meaning = (t.get("term") or "").strip(), (t.get("meaning") or t.get("summary") or "").strip()
        reason = None
        if not term or not meaning or not t.get("category") or not t.get("categoryName") or not t.get("url"):
            reason = "빈 칸"
        elif banned(" ".join([term, t.get("reading") or "", meaning])):
            reason = "금칙어"
        elif term in seen or term in {c["term"] for c in chosen}:
            reason = "12개월 안에 이미 냄"
        if reason:
            skipped.append(f"{term}({reason})")
            continue
        chosen.append({"term": term, "reading": (t.get("reading") or "").strip(), "summary": meaning,
                       "source": "위키백과", "url": t["url"], "category": t["category"],
                       "categoryName": t["categoryName"]})
        if len(chosen) == PER_DAY:
            break
    return chosen, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--source")
    args = parser.parse_args()
    today = datetime.now(KST).date()
    if args.date:
        day = date.fromisoformat(args.date)
        if day > today:
            sys.exit(f"{day}: 오늘({today})보다 뒤 날짜는 올리지 않습니다")
        if day < FIRST_DAY:
            sys.exit(f"{day}: {FIRST_DAY} 전 날짜는 앱에 실린 용어로 이미 열렸습니다 — 바꾸지 않습니다")
        publish(day, args.source)
        return
    # 날짜를 안 주면 오늘과 지난 이틀 중 빈 날을 채운다 — GitHub 예약 실행이 늦거나 빠진 날을 다음 회차가 메운다(2026-09-24)
    for back in (BACKFILL_DAYS, 1, 0):
        day = today - timedelta(days=back)
        if day >= FIRST_DAY:
            publish(day, None)


def publish(day, source):
    month = day.isoformat()[:7]
    path = OUT / f"{month}.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "month": month, "days": {}}
    if len(data["days"].get(day.isoformat(), [])) >= PER_DAY:
        print(f"{day}: 이미 {PER_DAY}개 — 그대로 둡니다")
        return

    if source:
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        url = SOURCE.format(y=day.year, md=day.strftime("%m-%d"))
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as error:   # 아직 안 채워졌으면 다음 회차가 잇는다
            print(f"{day}: 원본을 받지 못했습니다 — {error}")
            return
    raw = raw.get("terms", []) if isinstance(raw, dict) else raw

    chosen, skipped = pick(raw, day)
    if skipped:
        print("뺀 것:", ", ".join(skipped))
    if not chosen:
        print(f"{day}: 올릴 용어가 없습니다")
        return
    data["days"][day.isoformat()] = chosen
    data["days"] = dict(sorted(data["days"].items()))
    OUT.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{day}: {len(chosen)}개 — {', '.join(c['term'] for c in chosen)}")


if __name__ == "__main__":
    main()
