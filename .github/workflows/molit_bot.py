#!/usr/bin/env python3
import os, re, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

BASE = "https://www.molit.go.kr"
LIST_PATH = "/USR/NEWS/m_71/lst.jsp"
DETAIL_PATH = "/USR/NEWS/m_71/dtl.jsp"

# 원하는 분야만: 주택토지, 국토도시, 일반
CATEGORY_TO_SECTION = {
    "주택토지": "p_sec_2",
    "국토도시": "p_sec_9",
    "일반": "p_sec_1",
}

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")
RUN_TIME_HOUR = int(os.getenv("RUN_TIME_HOUR", "18"))   # KST 기준 (기본 18시)
TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (+Telegram notifier for MOLIT press releases)"
}

def send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("환경변수 BOT_TOKEN/CHAT_ID가 비어 있습니다.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }, timeout=TIMEOUT)

def get_soup(url: str, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_list_rows(soup: BeautifulSoup):
    """
    목록 테이블에서 (제목, 링크, 분야, 등록일[YYYY-MM-DD]) 추출
    """
    rows = []
    # 안내 문구 포함되어 있어도 a 태그가 있는 행면 충분
    for a in soup.select("a[href*='dtl.jsp?id=']"):
        title = a.get_text(strip=True)
        href = a.get("href")
        link = urljoin(BASE, href)

        # 같은 행에서 '분야', '등록일' 텍스트가 같은 줄에 있음
        tr = a.find_parent("tr")
        if not tr: 
            continue
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        # 일반적으로 [번호, 제목, 분야, 등록일, 조회]
        if len(tds) >= 4:
            category = tds[-3]  # '분야'
            date_str = tds[-2]  # '등록일' (YYYY-MM-DD)
        else:
            category, date_str = "", ""

        rows.append({
            "title": title,
            "link": link,
            "category": category,
            "date_str": date_str
        })
    return rows

def parse_detail_datetime_kst(detail_html: str):
    """
    상세 페이지에서 '등록일 2025-08-12 11:00' 형태를 찾아 datetime(KST) 변환
    """
    m = re.search(r"등록일\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})", detail_html)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))

def fetch_recent_for_section(section_code: str, section_name: str, since_kst: datetime, now_kst: datetime, max_pages: int = 3):
    """
    지정 섹션(분야)에서 최근 24시간 후보를 수집.
    목록에서 오늘/어제 글만 후보로 잡고, 상세에서 '등록일 시각'으로 최종 필터
    """
    items = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        params = {
            "search_section": section_code,
            "lcmspage": page,
            "psize": 10,
            # 기본 검색 파라미터는 페이지 네비게이션을 보면 자동으로 붙는 값들이 있으나 필수는 아님
        }
        soup = get_soup(urljoin(BASE, LIST_PATH), params=params)
        rows = parse_list_rows(soup)
        if not rows:
            break

        stop_paging = False
        for row in rows:
            # 목록은 날짜만 있으니 오늘/어제만 후보로
            try:
                row_date = datetime.strptime(row["date_str"], "%Y-%m-%d").date()
            except Exception:
                row_date = None
            if row_date and row_date < (now_kst - timedelta(days=1)).date():
                # 이 섹션은 최근 24시간 범위를 벗어난 날짜까지 내려왔으므로 다음 페이지 불필요
                stop_paging = True
                continue

            # 상세 접속하여 등록일 '시:분' 확보
            try:
                detail = session.get(row["link"], timeout=TIMEOUT)
                detail.raise_for_status()
            except Exception:
                continue

            dt_kst = parse_detail_datetime_kst(detail.text)
            if not dt_kst:
                continue
            if since_kst <= dt_kst <= now_kst:
                items.append({
                    "dt": dt_kst,
                    "title": row["title"],
                    "link": row["link"],
                    "category": section_name
                })

        if stop_paging:
            break

        # 예의상 짧은 쉬기(과도한 요청 방지)
        time.sleep(0.5)

    return items

def main():
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    since_kst = now_kst - timedelta(hours=24)

    wanted = ["주택토지", "국토도시", "일반"]  # 요청하신 3개만
    all_items = []

    for name in wanted:
        code = CATEGORY_TO_SECTION[name]
        all_items.extend(fetch_recent_for_section(code, name, since_kst, now_kst))

    if not all_items:
        send(f"국토교통부 보도자료 (지난 24시간, 3개 분야)\n기준: {now_kst:%Y-%m-%d %H:%M} KST\n\n신규 보도자료가 없습니다.")
        return

    # 최신순 정렬
    all_items.sort(key=lambda x: x["dt"], reverse=True)

    # 카테고리별로 묶어서 출력
    header = f"국토교통부 보도자료 (지난 24시간, 주택토지·국토도시·일반)\n기준: {now_kst:%Y-%m-%d %H:%M} KST"
    lines = [header, ""]
    last_cat = None
    for it in all_items:
        if it["category"] != last_cat:
            lines.append(f"[{it['category']}]")
            last_cat = it["category"]
        lines.append(f"• {it['title']}\n  - 등록: {it['dt']:%Y-%m-%d %H:%M}\n  - 링크: {it['link']}")

    # 텔레그램 4096자 제한 고려 분할 전송
    chunks, buf = [], 0
    cur = []
    for line in lines:
        if buf + len(line) + 1 > 3500:
            chunks.append("\n".join(cur)); cur, buf = [], 0
        cur.append(line); buf += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))

    for c in chunks:
        send(c)
        time.sleep(0.3)

if __name__ == "__main__":
    main()
