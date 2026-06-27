# -*- coding: utf-8 -*-
"""업체 연락처 수집기 (여우알바 + 퀸알바).

고객 PC에서 실행하는 단일 GUI 도구.
1) 각 사이트에서 본인인증(비회원 인증)을 직접 완료한 뒤
2) 버튼을 누르면 로그인된 세션 쿠키로 모든 상세 광고를 자동 수집하고
3) 바탕화면에 엑셀(업체명/담당자/전화번호)을 저장한다.

여우알바 상세표는 '담당자' 헤더 이후 <font color="#525252"> 값들이
[업종, 담당자, 상호(업체명), 주소, 연락처(전화), 카톡] 순서(고객 샘플 80/80 검증).
퀸알바는 라벨 셀(>상호<, >담당자<, >전화번호<) 다음 첫 비어있지 않은 <td> 값.
"""
import os
import re
import sys
import time
import threading

# --- 한글 print 안전 (cp1252 콘솔에서 UnicodeEncodeError 방지) ---
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import requests

# --- 실행 모드 플래그 ---
EXTRACTOR_AUTO = os.environ.get("EXTRACTOR_AUTO") == "1"
EXTRACTOR_HEADLESS = os.environ.get("EXTRACTOR_HEADLESS") == "1"
EXTRACTOR_MAX = int(os.environ.get("EXTRACTOR_MAX", "0"))  # 0=전체, N=상세 N건 제한

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MAX_PAGES = 400  # 무한 루프 방지 상한

# ===================== 공통 파서 유틸 =====================
VAL_RE = re.compile(r'<font color="#525252">(.*?)</font>', re.S | re.I)
SP = lambda w: r'\s*'.join(map(re.escape, w))
CLEAN = lambda s: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s).replace('&nbsp;', ' ')).strip()
PHONE_RE = re.compile(r'0\d{1,2}[-. )]\d{3,4}[-. ]\d{4}')


def parse_fox(html):
    m = re.search(SP('담당자'), html)
    if not m:
        return None
    vals = [CLEAN(mm.group(1)) for mm in VAL_RE.finditer(html) if mm.start() > m.start()]
    if len(vals) < 5:
        return None
    phone = vals[4]
    if not PHONE_RE.fullmatch(phone):
        pm = PHONE_RE.search(' '.join(vals[3:7]))
        phone = pm.group(0) if pm else phone
    if not PHONE_RE.search(phone):
        return None
    return {
        '업체명': vals[2], '담당자': vals[1],
        '전화번호': re.sub(r'[ .)]', '-', phone).strip('-'),
    }


def field_queen(label, html):
    m = re.search(r'>\s*' + re.escape(label) + r'\s*<', html)
    if not m:
        return ''
    for c in re.findall(r'<td[^>]*>(.*?)</td>', html[m.end():m.end() + 500], re.S | re.I):
        v = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ')).strip()
        if v:
            return v
    return ''


def parse_queen(html):
    name = field_queen('상호', html)
    mgr = field_queen('담당자', html)
    phone = field_queen('전화번호', html)
    pm = PHONE_RE.search(phone)
    if not pm:
        return None
    return {
        '업체명': name, '담당자': mgr,
        '전화번호': re.sub(r'[ .)]', '-', pm.group(0)).strip('-'),
    }


# ===================== 사이트 URL =====================
# 실측: foxalba 의 실제 경로는 /offer/ 이며 /job/ 은 404.
FOX_BASE = "https://www.foxalba.com"
FOX_LIST = FOX_BASE + "/offer/offer_jobpart.asp?page={page}"
FOX_DETAIL = FOX_BASE + "/offer/offer_content.asp?idx={idx}"
FOX_DETAIL_RE = re.compile(r'offer_content\.asp\?idx=([0-9]+)', re.I)

QUEEN_BASE = "https://www.queenalba.net"
QUEEN_ENTRY = QUEEN_BASE + "/guin_list.php"
QUEEN_LIST = QUEEN_BASE + "/guin/guin_list.php?pg={pg}"
QUEEN_DETAIL = QUEEN_BASE + "/guin/guin_detail.php?num={num}&pg={pg}&cou={cou}"
QUEEN_DETAIL_RE = re.compile(r'guin_detail\.php\?num=([0-9]+)&pg=([0-9]+)&cou=([0-9]+)', re.I)


# ===================== Selenium 드라이버 =====================
def make_driver(headless):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-popup-blocking")  # 퀸알바 본인인증 팝업 허용
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    drv = webdriver.Chrome(options=opts)  # Selenium Manager 가 드라이버 자동 설치
    try:
        drv.set_page_load_timeout(45)
    except Exception:
        pass
    return drv


def session_from_driver(driver):
    """로그인된 Chrome 세션의 쿠키를 requests.Session 으로 옮긴다(상세 페이지 고속 수집)."""
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    try:
        for c in driver.get_cookies():
            try:
                sess.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
            except Exception:
                sess.cookies.set(c["name"], c["value"])
    except Exception:
        pass
    return sess


def _get(sess, url, encoding=None, referer=None):
    headers = {"Referer": referer} if referer else {}
    r = sess.get(url, headers=headers, timeout=30)
    if encoding:
        r.encoding = encoding
    return r.text


# ===================== 여우알바 수집 =====================
def scrape_fox(sess, log, max_items=0):
    idxs = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        try:
            html = _get(sess, FOX_LIST.format(page=page), encoding="euc-kr")
        except Exception as e:
            log(f"  목록 {page}페이지 오류: {e}")
            break
        found = FOX_DETAIL_RE.findall(html)
        new = [i for i in found if i not in seen]
        for i in found:
            seen.add(i)
        log(f"페이지 {page}... 상세링크 {len(found)}개 (신규 {len(new)}개)")
        if not found:
            break
        if not new and page > 1:
            break
        idxs.extend(new)
        if max_items and len(idxs) >= max_items:
            idxs = idxs[:max_items]
            break
        time.sleep(0.2)

    rows, phones = [], set()
    total = len(idxs)
    for n, idx in enumerate(idxs, 1):
        try:
            html = _get(sess, FOX_DETAIL.format(idx=idx), encoding="euc-kr",
                        referer=FOX_LIST.format(page=1))
        except Exception:
            continue
        r = parse_fox(html)
        if not r:
            continue
        if r['전화번호'] in phones:
            continue
        phones.add(r['전화번호'])
        rows.append(r)
        if n % 5 == 0 or n == total:
            log(f"연락처 수집 중 ({len(rows)}건)... {n}/{total}")
        time.sleep(0.05)
    log(f"여우알바 수집 완료: {len(rows)}건")
    return rows


# ===================== 퀸알바 수집 =====================
def scrape_queen(sess, log, max_items=0):
    targets = []  # (num, pg, cou)
    seen = set()
    for pg in range(1, MAX_PAGES + 1):
        try:
            html = _get(sess, QUEEN_LIST.format(pg=pg), encoding="utf-8", referer=QUEEN_ENTRY)
        except Exception as e:
            log(f"  목록 {pg}페이지 오류: {e}")
            break
        found = QUEEN_DETAIL_RE.findall(html)
        new = [t for t in found if (t[0], t[1], t[2]) not in seen]
        for t in found:
            seen.add((t[0], t[1], t[2]))
        log(f"페이지 {pg}... 상세링크 {len(found)}개 (신규 {len(new)}개)")
        if not found:
            break
        if not new and pg > 1:
            break
        targets.extend(new)
        if max_items and len(targets) >= max_items:
            targets = targets[:max_items]
            break
        time.sleep(0.2)

    rows, phones = [], set()
    total = len(targets)
    for n, (num, pg, cou) in enumerate(targets, 1):
        url = QUEEN_DETAIL.format(num=num, pg=pg, cou=cou)
        try:
            html = _get(sess, url, encoding="utf-8", referer=QUEEN_LIST.format(pg=pg))
        except Exception:
            continue
        r = parse_queen(html)
        if not r:
            continue
        if r['전화번호'] in phones:
            continue
        phones.add(r['전화번호'])
        rows.append(r)
        if n % 5 == 0 or n == total:
            log(f"연락처 수집 중 ({len(rows)}건)... {n}/{total}")
        time.sleep(0.05)
    log(f"퀸알바 수집 완료: {len(rows)}건")
    return rows


# ===================== 엑셀 출력 =====================
def desktop_path():
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"), os.path.join(home, "바탕 화면"), home):
        if os.path.isdir(cand):
            return cand
    return home


def write_excel(fox_rows, queen_rows, path):
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill(start_color="1452CC", end_color="1452CC", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    widths = {'업체명': 24, '담당자': 12, '전화번호': 18, '사이트': 12}

    wb = Workbook()

    def fill_sheet(ws, cols, rows):
        ws.append(cols)
        for ci, col in enumerate(cols, 1):
            c = ws.cell(row=1, column=ci)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(ci)].width = widths.get(col, 16)
        for r in rows:
            ws.append([r.get(c, '') for c in cols])
        ws.freeze_panes = "A2"

    ws1 = wb.active
    ws1.title = "여우알바"
    fill_sheet(ws1, ['업체명', '담당자', '전화번호'], fox_rows)

    ws2 = wb.create_sheet("퀸알바")
    fill_sheet(ws2, ['업체명', '담당자', '전화번호'], queen_rows)

    # 통합(중복제거: 전화번호 기준)
    merged, seen = [], set()
    for site, rows in (("여우알바", fox_rows), ("퀸알바", queen_rows)):
        for r in rows:
            key = r['전화번호']
            if key in seen:
                continue
            seen.add(key)
            d = dict(r)
            d['사이트'] = site
            merged.append(d)
    ws3 = wb.create_sheet("통합(중복제거)")
    fill_sheet(ws3, ['업체명', '담당자', '전화번호', '사이트'], merged)

    wb.save(path)
    return len(merged)


# ===================== GUI =====================
def run_gui():
    import tkinter as tk
    from tkinter import scrolledtext

    state = {"fox": [], "queen": [], "driver": None, "fox_done": False, "queen_done": False}

    root = tk.Tk()
    root.title("업체 연락처 수집기")
    root.geometry("760x560")

    log_widget = scrolledtext.ScrolledText(root, wrap="word", font=("Malgun Gothic", 10))
    log_widget.pack(fill="both", expand=True, padx=10, pady=(10, 6))

    def log(msg):
        def _append():
            log_widget.insert("end", str(msg) + "\n")
            log_widget.see("end")
        try:
            log_widget.after(0, _append)
        except Exception:
            print(msg)

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=(0, 10))

    def open_browser(url, label, fresh=False):
        def task():
            try:
                # 새 세션이 필요하면(예: 여우 수집 완료 후 퀸 시작) 기존 드라이버를
                # 무조건 정리하고 새 webdriver.Chrome 을 만든다. 오래된(stale) 세션을
                # 재사용하면 'invalid session id' 오류가 난다.
                if fresh and state["driver"] is not None:
                    try:
                        state["driver"].quit()
                    except Exception:
                        pass
                    state["driver"] = None
                if state["driver"] is None:
                    log("브라우저를 여는 중...")
                    state["driver"] = make_driver(False)
                else:
                    # 재사용 전에 세션이 살아있는지 확인. 죽었으면 새로 만든다.
                    try:
                        _ = state["driver"].current_url
                    except Exception:
                        try:
                            state["driver"].quit()
                        except Exception:
                            pass
                        log("이전 브라우저 세션이 종료되어 새 창을 엽니다...")
                        state["driver"] = make_driver(False)
                state["driver"].get(url)
                log("브라우저를 열었습니다. 비회원 본인인증을 완료 후 아래 버튼을 눌러주세요.")
            except Exception as e:
                log(f"브라우저 오류: {e}")
                # 오류 발생 시 깨진 드라이버 상태를 정리해 다음 클릭이 새 세션을 만들도록.
                try:
                    if state["driver"] is not None:
                        state["driver"].quit()
                except Exception:
                    pass
                state["driver"] = None
        threading.Thread(target=task, daemon=True).start()

    def start_fox():
        def task():
            try:
                btn_fox_go.config(state="disabled")
                sess = session_from_driver(state["driver"]) if state["driver"] else requests.Session()
                if not state["driver"]:
                    sess.headers.update({"User-Agent": UA})
                log("여우알바 수집을 시작합니다...")
                state["fox"] = scrape_fox(sess, log, EXTRACTOR_MAX)
                state["fox_done"] = True
                # 여우 수집이 끝나면 여우 드라이버를 명시적으로 종료하고 None 으로 비운다.
                # 퀸알바는 반드시 새 Chrome 세션으로 시작해야 하며, 닫힌 여우 세션을
                # 재사용하면 'invalid session id' 오류가 난다.
                if state["driver"] is not None:
                    try:
                        state["driver"].quit()
                    except Exception:
                        pass
                    state["driver"] = None
                btn_queen_login.config(state="normal")
                btn_save.config(state="normal")
            except Exception as e:
                log(f"여우알바 수집 오류: {e}")
                btn_fox_go.config(state="normal")
        threading.Thread(target=task, daemon=True).start()

    def start_queen():
        def task():
            try:
                btn_queen_go.config(state="disabled")
                sess = session_from_driver(state["driver"]) if state["driver"] else requests.Session()
                if not state["driver"]:
                    sess.headers.update({"User-Agent": UA})
                log("퀸알바 수집을 시작합니다...")
                state["queen"] = scrape_queen(sess, log, EXTRACTOR_MAX)
                state["queen_done"] = True
                btn_save.config(state="normal")
            except Exception as e:
                log(f"퀸알바 수집 오류: {e}")
                btn_queen_go.config(state="normal")
        threading.Thread(target=task, daemon=True).start()

    def save_excel():
        def task():
            try:
                path = os.path.join(desktop_path(), "업체연락처_여우알바_퀸알바.xlsx")
                n = write_excel(state["fox"], state["queen"], path)
                log(f"저장 완료: {path.replace(os.sep, '/')}  (통합 {n}건)")
                try:
                    os.startfile(path)  # noqa: only on Windows
                except Exception:
                    pass
            except Exception as e:
                log(f"저장 오류: {e}")
        threading.Thread(target=task, daemon=True).start()

    # Step 1 여우알바
    tk.Label(btn_frame, text="① 여우알바", font=("Malgun Gothic", 9, "bold")).grid(row=0, column=0, padx=4, pady=2, sticky="w")
    tk.Button(btn_frame, text="여우알바 로그인 시작",
              command=lambda: open_browser(FOX_BASE + "/", "여우알바")).grid(row=1, column=0, padx=4, pady=2, sticky="ew")
    btn_fox_go = tk.Button(btn_frame, text="여우알바 인증 완료 → 수집 시작", command=start_fox)
    btn_fox_go.grid(row=1, column=1, padx=4, pady=2, sticky="ew")

    # Step 2 퀸알바
    tk.Label(btn_frame, text="② 퀸알바", font=("Malgun Gothic", 9, "bold")).grid(row=2, column=0, padx=4, pady=2, sticky="w")
    btn_queen_login = tk.Button(btn_frame, text="퀸알바 로그인 시작", state="disabled",
                                command=lambda: open_browser(QUEEN_ENTRY, "퀸알바", fresh=True))
    btn_queen_login.grid(row=3, column=0, padx=4, pady=2, sticky="ew")
    btn_queen_go = tk.Button(btn_frame, text="퀸알바 인증 완료 → 수집 시작", command=start_queen)
    btn_queen_go.grid(row=3, column=1, padx=4, pady=2, sticky="ew")

    # Step 3 저장
    tk.Label(btn_frame, text="③ 저장", font=("Malgun Gothic", 9, "bold")).grid(row=4, column=0, padx=4, pady=2, sticky="w")
    btn_save = tk.Button(btn_frame, text="엑셀 저장", state="disabled", command=save_excel)
    btn_save.grid(row=5, column=0, padx=4, pady=2, sticky="ew")

    btn_frame.columnconfigure(0, weight=1)
    btn_frame.columnconfigure(1, weight=1)

    log("업체 연락처 수집기입니다. ① 여우알바 로그인 시작 버튼부터 진행하세요.")

    # GUI 구성 자체 검증(프리징 exe 의 tkinter 번들 확인용)
    gms = int(os.environ.get("EXTRACTOR_GUITEST_MS", "0"))
    if os.environ.get("EXTRACTOR_GUITEST") == "1" and gms > 0:
        root.after(gms, root.destroy)

    root.mainloop()


# ===================== AUTO(헤드리스 일괄) =====================
def run_auto():
    def log(m):
        print(m, flush=True)
    log("EXTRACTOR_AUTO: 헤드리스 일괄 수집 시작")
    driver = None
    try:
        driver = make_driver(EXTRACTOR_HEADLESS)
        driver.get(FOX_BASE + "/")
        time.sleep(1.0)
    except Exception as e:
        log(f"드라이버 초기화 경고(쿠키 없이 진행): {e}")
    sess = session_from_driver(driver) if driver else requests.Session()
    sess.headers.update({"User-Agent": UA})

    fox = scrape_fox(sess, log, EXTRACTOR_MAX)
    try:
        if driver:
            driver.get(QUEEN_ENTRY)
            time.sleep(1.0)
            sess = session_from_driver(driver)
            sess.headers.update({"User-Agent": UA})
    except Exception:
        pass
    queen = scrape_queen(sess, log, EXTRACTOR_MAX)

    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    path = os.path.join(desktop_path(), "업체연락처_여우알바_퀸알바.xlsx")
    n = write_excel(fox, queen, path)
    log(f"저장 완료: {path.replace(os.sep, '/')}  (여우 {len(fox)} / 퀸 {len(queen)} / 통합 {n})")


def main():
    if EXTRACTOR_AUTO:
        run_auto()
    else:
        run_gui()


if __name__ == "__main__":
    main()
