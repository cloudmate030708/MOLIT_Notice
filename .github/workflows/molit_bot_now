#!/usr/bin/env python3
import os, re, time, json, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
from bs4 import BeautifulSoup

BASE = "https://www.molit.go.kr"
LIST_PATH = "/USR/NEWS/m_71/lst.jsp"

# 요청하신 3개 분야만
CATEGORY_TO_SECTION = {
    "주택토지": "p_sec_2",
    "국토도시": "p_sec_9",
    "일반": "p_sec_1",
}

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID   = os.getenv("CHAT_ID")  # 예: @MOLIT_bot 또는 숫자ID(-100...)
TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (+MOLIT press bot)"}

# 중복 방지 캐시 파일
CACHE_PATH = os.getenv("CACHE_PATH", ".molit_sent.json")
MAX_CACHE = 300  # 최대 300개 보관

SUMMARY_CHARS = int(os.getenv("SUMMARY_CHARS", "220"))  # 요약 길이

def send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("환경변수 BOT_TOKEN/CHAT_ID가 비어 있습니다.")
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=TIMEOUT
    )
    r.raise_for_status()

def get_soup(url: str, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_list_rows(soup: BeautifulSoup):
    rows = []
    for a in soup.select("a[href*='USR/NEWS/m_71/dtl.jsp']"):
        title = a.get_text(strip=True)
        href = a.get("href")
        link = urljoin(BASE, href)
        tr = a.find_parent("tr")
        if not tr:
            continue
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        # [번호, 제목, 분야, 등록일, 조회] 형태가 일반적
        category = tds[-3] if len(tds) >= 4 else ""
        date_str = tds[-2] if len(tds) >= 4 else ""  # YYYY-MM-DD
        rows.append({"title": title, "link": link, "category": category, "date_str": date_str})
    return rows

def parse_detail_datetime_kst(html: str):
    m = re.search(r"등록일\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})", html)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))

def extract_summary(html: str, limit: int = 220) -> str:
    """
    상세 본문에서 텍스트를 모아 앞부분만 요약으로 사용.
    다양한 게시판 스킨을 고려해 넓게 탐색 → 첫 1~2문장 정도 잘라냄.
    """
    soup = BeautifulSoup(html, "lxml")

    candidates = [
        # 자주 쓰이는 컨테이너 후보
        "#viewCon", ".board_view", ".view", ".bo_view", ".bo_content", ".bo_text",
        ".bbsView", ".contents", "#contents", "#content"
    ]
    text = ""
    for sel in candidates:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            text = el.get_text(separator=" ", strip=True)
            break
    if not text:
        text = soup.get_text(separator=" ", strip=True)

    # 공백 정리
    text = re.sub(r"\s+", " ", text)

    # 너무 긴 건 앞부분만 사용
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text

def load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("links", []))
    except Exception:
        return set()

def save_cache(links_set):
    try:
        links = list(links_set)
        if len(links) > MAX_CACHE:
            links = links[-MAX_CACHE:]
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"links": links}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 캐시 저장 실패는 무시

def fetch_recent_for_section(section_code: str, section_name: str, since_kst: datetime, now_kst: datetime, max_pages: int = 3):
    items = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        params = {"search_section": section_code, "lcmspage": page, "psize": 10}
        soup = get_soup(urljoin(BASE, LIST_PATH), params=params)
        rows = parse_list_rows(soup)
        if not rows:
            break

        stop_paging = False
        for row in rows:
            try:
                row_date = datetime.strptime(row["date_str"], "%Y-%m-%d").date()
            except Exception:
                row_date = None
            if row_date and row_date < (now_kst - timedelta(days=1)).date():
                stop_paging = True
                continue

            try:
                detail = session.get(row["link"], timeout=TIMEOUT)
                detail.raise_for_status()
            except Exception:
                continue

            dt_kst = parse_detail_datetime_kst(detail.text)
            if not dt_kst:
                continue
            if since_kst <= dt_kst <= now_kst:
                summary = extract_summary(detail.text, limit=SUMMARY_CHARS)
                items.append({
                    "dt": dt_kst,
                    "title": row["title"],
                    "link": row["link"],
                    "category": section_name,
                    "summary": summary
                })

        if stop_paging:
            break
        time.sleep(0.4)
    return items

def main():
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    since_kst = now_kst - timedelta(hours=24)

    wanted = ["주택토지", "국토도시", "일반"]
    all_items = []
    for name in wanted:
        code = CATEGORY_TO_SECTION[name]
        all_items.extend(fetch_recent_for_section(code, name, since_kst, now_kst))

    # 캐시 로드 및 중복 제거
    sent = load_cache()
    new_items = [it for it in all_items if it["link"] not in sent]

    if not new_items:
        send(f"국토교통부 보도자료 (지난 24시간, 주택토지·국토도시·일반)\n기준: {now_kst:%Y-%m-%d %H:%M} KST\n\n신규 보도자료가 없습니다. (중복 제외)")
        return

    new_items.sort(key=lambda x: x["dt"], reverse=True)

    header = f"국토교통부 보도자료 (지난 24시간, 주택토지·국토도시·일반)\n기준: {now_kst:%Y-%m-%d %H:%M} KST"
    lines = [header, ""]
    last_cat = None
    for it in new_items:
        if it["category"] != last_cat:
            lines.append(f"[{it['category']}]")
            last_cat = it["category"]
        lines.append(
            f"• {it['title']}\n"
            f"  - 등록: {it['dt']:%Y-%m-%d %H:%M}\n"
            f"  - 요약: {it['summary']}\n"
            f"  - 링크: {it['link']}"
        )

    # 길면 분할 전송
    chunk, buf = [], 0
    for line in lines:
        if buf + len(line) + 1 > 3500:
            send("\n".join(chunk))
            chunk, buf = [], 0
        chunk.append(line); buf += len(line) + 1
    if chunk:
        send("\n".join(chunk))

    # 캐시 업데이트
    for it in new_items:
        sent.add(it["link"])
    save_cache(sent)

if __name__ == "__main__":
    main()
