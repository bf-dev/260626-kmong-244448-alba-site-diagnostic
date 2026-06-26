# -*- coding: utf-8 -*-
"""
여우알바 / 퀸알바 사이트 구조 자동 진단 도구 (고객 PC 실행용, GUI)
--------------------------------------------------------
콘솔 없이 창(GUI)으로 실행됩니다.
  1) [시작하기] 를 누르면 사이트가 브라우저 창으로 열립니다.
  2) 브라우저에서 '비회원 본인인증'을 1회 직접 완료해 주세요.
     (인증은 고객님 본인 명의로, 고객님 PC에서만 진행됩니다.)
  3) 인증이 끝나면 프로그램 창의 [인증 완료 - 다음] 버튼을 누르세요.
  4) 도구가 목록의 모든 페이지를 자동으로 넘기고, 구조 확인용 하위(상세) 페이지
     샘플과 세션 쿠키를 저장합니다. (몇 분이면 끝납니다)
  5) 끝나면 바탕화면에 "진단폴더 이거 보내주세요.zip" 이 생성됩니다.
  6) 그 zip 파일 하나만 보내주시면 나머지는 저희가 진행합니다.

환경변수(검증/자동화용, 일반 고객은 신경쓰지 않으셔도 됩니다):
  DIAG_AUTO=1      GUI 없이 자동(헤드리스) 일괄 실행 (CI 검증용)
  DIAG_HEADLESS=1  브라우저 창 없이 실행
  DIAG_SITES=foxalba,queenalba   대상 사이트 제한
  DIAG_MAX_DETAIL=80 사이트별 상세 저장 개수(기본 80 샘플, 0=무제한/전수)
  DIAG_MAX_PAGES=300 목록 페이지 자동탐색 상한(안전장치)
"""

import os
import re
import sys
import json
import time
import shutil
import zipfile
import datetime
import threading

DESKTOP_FOLDER_NAME = "진단폴더 이거 보내주세요"

# 콘솔 코드페이지가 한글을 못 받는 환경(영문 Windows cp1252 등)에서도
# 한글 출력이 깨지거나 죽지 않도록 표준 출력 인코딩을 UTF-8 로 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def envint(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


AUTO = os.environ.get("DIAG_AUTO") == "1"
HEADLESS = os.environ.get("DIAG_HEADLESS") == "1"
MAX_DETAIL = envint("DIAG_MAX_DETAIL", 80)       # 진단용 사이트당 상세 샘플 기본 80건 (0=무제한)
MAX_PAGES = envint("DIAG_MAX_PAGES", 300)
ONLY_SITES = [s for s in os.environ.get("DIAG_SITES", "").split(",") if s]

# ---- 사이트 정의 -----------------------------------------------------------
SITES = {
    "foxalba": {
        "label": "여우알바 (foxalba.com)",
        "entry": "https://www.foxalba.com/",
        # {pg} 자리에 페이지 번호. 1페이지부터 새 항목이 없을 때까지 자동 순회.
        "list_tpl": "https://www.foxalba.com/offer/offer_jobpart.asp?page={pg}&orderby01=o_orderday&orderby02=20&orderby03=desc",
        "detail_regex": r"offer_content\.asp\?idx=([0-9]+)",
        "detail_tpl": "https://www.foxalba.com/offer/offer_content.asp?idx={id}",
    },
    "queenalba": {
        "label": "퀸알바 (queenalba.net)",
        "entry": "https://queenalba.net/adult_index.php",
        "list_tpl": "https://queenalba.net/main/list.php?page={pg}",
        # 인증 후에야 상세 링크가 노출되므로 일반 패턴으로 자동 탐색 (href 그대로 사용)
        "detail_regex": r"(?:view|content|read|detail)[a-z_]*\.php\?[^\"'<> ]*?(?:idx|no|num|wr_id|seq|uid|id)=[0-9]+",
        "detail_tpl": None,
    },
}

# 진행 로그/인증대기 흐름은 콜백으로 주입(콘솔 또는 GUI 양쪽 지원).
LOG_SINK = None          # callable(str) or None -> print
WAIT_CB = None           # callable(label) -> blocks until user confirms auth


def log(msg):
    if LOG_SINK:
        try:
            LOG_SINK(msg)
        except Exception:
            pass
        return
    try:
        print(msg, flush=True)
    except Exception:
        pass


def desktop_dir():
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "바탕 화면")):
        if os.path.isdir(cand):
            return cand
    return home


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-popup-blocking")  # 퀸알바 본인인증 팝업 허용
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    drv = webdriver.Chrome(options=opts)  # Selenium Manager 가 드라이버 자동 설치
    # 게이트(본인인증/리다이렉트)에서 무한 대기하지 않도록 페이지 로드 상한.
    try:
        drv.set_page_load_timeout(45)
    except Exception:
        pass
    return drv


def wait_for_user(label):
    if AUTO:
        log(f">>> [{label}] DIAG_AUTO: 인증 대기 생략")
        return
    if WAIT_CB:
        WAIT_CB(label)
        return
    input(f"\n>>> [{label}] 인증을 완료하셨으면 Enter 를 눌러주세요... ")


def snap(driver, path):
    """화면 캡처(진단/검증용). 실패해도 무시."""
    try:
        driver.save_screenshot(path)
    except Exception as e:
        log(f"  (스크린샷 실패: {e})")


def ensure_live_window(driver):
    """본인인증 팝업(window.open) 이후 활성 창이 바뀌거나 닫혀도 살아있는 창으로 복구.
    퀸알바는 인증을 별도 팝업창에서 진행해 원래 창 핸들이 무효화될 수 있으므로,
    살아있는 창으로 전환하고(없으면 새 탭 생성) 크롤을 이어간다."""
    try:
        handles = driver.window_handles
    except Exception:
        handles = []
    if handles:
        for h in reversed(handles):   # 보통 인증 후 마지막 창이 본 화면
            try:
                driver.switch_to.window(h)
                return True
            except Exception:
                continue
    try:
        driver.switch_to.new_window("tab")  # 모든 창이 닫혔으면 같은 세션에 새 탭
        return True
    except Exception:
        return False


def save_netscape_cookies(cookies, path):
    lines = ["# Netscape HTTP Cookie File", "# saved by diagnose tool", ""]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path_ = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expiry", 0)) or 2147483647
        lines.append("\t".join([domain, flag, path_, secure, str(expiry),
                                 c.get("name", ""), c.get("value", "")]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def discover_links(html):
    hrefs = re.findall(r"href=[\"']([^\"'<> ]+)[\"']", html, re.I)
    id_links = [h for h in hrefs if re.search(r"(idx|no|num|wr_id|seq|uid|id)=[0-9]+", h, re.I)]
    patterns = {}
    for h in id_links:
        base = re.sub(r"=[0-9]+", "=N", h.split("//")[-1].split("?")[0])
        keys = ",".join(sorted(set(re.findall(r"([a-z_]+)=[0-9]+", h, re.I))))
        k = base + "?" + keys
        patterns[k] = patterns.get(k, 0) + 1
    return hrefs, id_links, patterns


def crawl_lists(driver, conf, site_dir, report):
    """1페이지부터 새 상세링크가 안 나올 때까지 자동 순회하며 모든 목록 HTML 저장."""
    all_ids, all_hrefs = [], []
    seen_ids = set()
    empty_streak = 0
    for pg in range(1, MAX_PAGES + 1):
        url = conf["list_tpl"].format(pg=pg)
        try:
            driver.get(url)
            time.sleep(1.2)
            html = driver.page_source
        except Exception as e:
            report.append(f"list page {pg} ERROR {e}")
            break
        with open(os.path.join(site_dir, f"list_{pg:03d}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        hrefs, id_links, patterns = discover_links(html)
        page_ids = re.findall(conf["detail_regex"], html, re.I)
        new = [x for x in page_ids if x not in seen_ids]
        for x in page_ids:
            seen_ids.add(x)
        all_ids += new
        all_hrefs += id_links
        report.append(f"  목록 {pg:03d}: size={len(html)} 상세링크={len(id_links)} 신규={len(new)}")
        log(f"  목록 {pg}페이지 저장 (상세링크 {len(id_links)}개, 신규 {len(new)}개)")
        if not page_ids and not id_links:
            empty_streak += 1
            if empty_streak >= 2:
                report.append(f"  -> {pg}페이지에서 신규 없음, 목록 순회 종료")
                break
        else:
            empty_streak = 0
        if not new and pg > 1:
            # 새 ID가 더 안 나오면 끝까지 본 것으로 간주(여우알바: 페이지 끝에서 반복)
            report.append(f"  -> {pg}페이지부터 신규 ID 없음, 목록 순회 종료")
            break
    return list(dict.fromkeys(all_ids)), list(dict.fromkeys(all_hrefs))


def crawl_details(driver, conf, site_dir, ids, hrefs, report):
    saved = 0
    limit = MAX_DETAIL if MAX_DETAIL > 0 else 10 ** 9
    if conf.get("detail_tpl"):
        targets = [conf["detail_tpl"].format(id=i) for i in ids]
    else:
        base = conf["entry"].rsplit("/", 1)[0]
        targets = [h if h.startswith("http") else base + "/" + h.lstrip("/") for h in hrefs]
    total = min(len(targets), limit)
    report.append(f"  상세 대상 {len(targets)}개 중 {total}개 저장 예정 (MAX_DETAIL={MAX_DETAIL})")
    log(f"  하위(상세) 페이지 {total}개 저장 시작...")
    for n, url in enumerate(targets):
        if saved >= limit:
            break
        try:
            driver.get(url)
            time.sleep(0.8)
            html = driver.page_source
        except Exception as e:
            report.append(f"  detail {url} ERROR {e}")
            continue
        idm = re.search(r"=([0-9]+)$|=([0-9]+)(?:&|$)", url)
        tag = (idm.group(1) or idm.group(2)) if idm else str(n + 1)
        with open(os.path.join(site_dir, f"detail_{tag}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        saved += 1
        if saved % 25 == 0:
            log(f"    ...하위 페이지 {saved}/{total} 저장")
    report.append(f"  상세(하위) 페이지 저장: {saved}개")
    log(f"  하위(상세) 페이지 {saved}개 저장 완료")
    return saved


def process_site(driver, key, conf, out_root):
    site_dir = os.path.join(out_root, key)
    os.makedirs(site_dir, exist_ok=True)
    report = [f"# {conf['label']}", f"entry: {conf['entry']}", ""]

    log("\n" + "=" * 50)
    log(f"[{conf['label']}] 브라우저에서 비회원 본인인증을 완료해 주세요.")
    log("=" * 50)
    try:
        driver.get(conf["entry"])
        time.sleep(1.5)
    except Exception as e:
        log(f"  (진입 페이지 로드 지연: {e})")
    snap(driver, os.path.join(site_dir, "_화면_01_진입.png"))
    wait_for_user(conf["label"])

    # 인증 팝업 이후 살아있는 창으로 복구하고, 대상 사이트 페이지로 이동해 세션을 확정.
    ensure_live_window(driver)
    for attempt in range(2):
        try:
            driver.get(conf["list_tpl"].format(pg=1))
            time.sleep(1.2)
            break
        except Exception as e:
            log(f"  (세션 확정 재시도 {attempt+1}: {e})")
            ensure_live_window(driver)
    snap(driver, os.path.join(site_dir, "_화면_02_인증후.png"))

    try:
        cookies = driver.get_cookies()
    except Exception as e:
        log(f"  (쿠키 읽기 재시도: {e})")
        ensure_live_window(driver)
        try:
            cookies = driver.get_cookies()
        except Exception:
            cookies = []
    save_netscape_cookies(cookies, os.path.join(site_dir, "cookies.txt"))
    with open(os.path.join(site_dir, "cookies.json"), "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    report.append(f"cookies: {len(cookies)}개 저장")
    log(f"  - 쿠키 {len(cookies)}개 저장")

    report.append("\n## 목록 자동 순회")
    ids, hrefs = crawl_lists(driver, conf, site_dir, report)
    report.append(f"\n고유 상세 ID(또는 링크): {len(ids) or len(hrefs)}개")
    log(f"  - 목록 순회 완료: 고유 상세 {len(ids) or len(hrefs)}개")

    report.append("\n## 하위(상세) 페이지 저장")
    saved = crawl_details(driver, conf, site_dir, ids, hrefs, report)

    with open(os.path.join(site_dir, "structure_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    return saved


def prepare_out_root():
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    desk = desktop_dir()
    out_root = os.path.join(desk, DESKTOP_FOLDER_NAME)
    if os.path.isdir(out_root):
        shutil.rmtree(out_root, ignore_errors=True)
    os.makedirs(out_root, exist_ok=True)
    with open(os.path.join(out_root, "_읽어주세요.txt"), "w", encoding="utf-8") as f:
        f.write("이 zip 을 그대로 보내주시면 됩니다.\n"
                "각 사이트 폴더: 목록(list_*.html), 하위페이지 샘플(detail_*.html),"
                " 구조 리포트(structure_report.txt), 세션 쿠키(cookies.txt/json)\n"
                f"생성: {stamp}\n")
    return desk, out_root


def zip_out_root(desk, out_root):
    zip_path = os.path.join(desk, DESKTOP_FOLDER_NAME + ".zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(out_root):
            for fn in files:
                full = os.path.join(root, fn)
                zf.write(full, os.path.relpath(full, os.path.dirname(out_root)))
    return zip_path


def run_collection(out_root):
    """드라이버 생성 -> 사이트별 처리. 총 저장 하위페이지 수 반환."""
    driver = make_driver()
    total = 0
    try:
        for key, conf in SITES.items():
            if ONLY_SITES and key not in ONLY_SITES:
                continue
            try:
                total += process_site(driver, key, conf, out_root)
            except Exception as e:
                log(f"[{key}] 처리 오류: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return total


# ---- 헤드리스/자동 일괄 실행 (CI 검증·자동화용) ----------------------------
def run_headless():
    log(__doc__)
    desk, out_root = prepare_out_root()
    try:
        total = run_collection(out_root)
    except Exception as e:
        log(f"\n[오류] 크롬을 열 수 없습니다. 크롬 설치를 확인해 주세요.\n상세: {e}")
        return 1
    zip_path = zip_out_root(desk, out_root)
    log("\n" + "=" * 50)
    log(f"완료. 바탕화면의 다음 파일을 보내주세요:\n  {zip_path}")
    log(f"총 저장 하위페이지: {total}개")
    log("=" * 50)
    return 0


# ---- GUI 실행 (고객용 기본) ------------------------------------------------
def run_gui():
    import tkinter as tk
    from tkinter import scrolledtext, messagebox

    global LOG_SINK, WAIT_CB

    root = tk.Tk()
    root.title("여우알바·퀸알바 사이트 진단 도구")
    root.geometry("640x560")
    root.configure(bg="#f4f5f7")

    auth_event = threading.Event()
    state = {"running": False}

    # ---- 위젯 ----
    head = tk.Label(root, text="여우알바 · 퀸알바 사이트 진단 도구",
                    font=("맑은 고딕", 15, "bold"), bg="#f4f5f7", fg="#1a1a1a")
    head.pack(pady=(16, 4))

    guide = tk.Label(
        root,
        text=("① [시작하기] → 브라우저가 열립니다.\n"
              "② 브라우저에서 '비회원 본인인증'을 1회 직접 완료하세요.\n"
              "③ 인증이 끝나면 아래 [인증 완료 - 다음] 버튼을 누르세요.\n"
              "④ 자동으로 목록·하위페이지 샘플·쿠키를 저장합니다. (몇 분 소요)\n"
              "⑤ 끝나면 바탕화면에 ' 진단폴더 이거 보내주세요.zip ' 이 생깁니다."),
        font=("맑은 고딕", 10), bg="#f4f5f7", fg="#333", justify="left")
    guide.pack(padx=20, pady=(0, 8), anchor="w")

    status = tk.Label(root, text="대기 중 — [시작하기] 를 눌러주세요.",
                      font=("맑은 고딕", 10, "bold"), bg="#eef1f6", fg="#1452cc",
                      anchor="w", padx=10, pady=8)
    status.pack(fill="x", padx=16)

    box = scrolledtext.ScrolledText(root, height=14, font=("Consolas", 9),
                                    bg="#101418", fg="#d6e2ff", insertbackground="#fff")
    box.pack(fill="both", expand=True, padx=16, pady=10)

    btns = tk.Frame(root, bg="#f4f5f7")
    btns.pack(fill="x", padx=16, pady=(0, 14))

    def set_status(txt, color="#1452cc"):
        status.config(text=txt, fg=color)

    def append(msg):
        box.insert("end", msg + "\n")
        box.see("end")

    def gui_log(msg):
        root.after(0, append, msg)

    def gui_wait(label):
        # 워커 스레드에서 호출 -> 메인 스레드에 버튼 활성화 요청 후 대기
        auth_event.clear()
        root.after(0, lambda: (
            set_status(f"[{label}] 브라우저에서 본인인증을 완료한 뒤 ▶ [인증 완료 - 다음] 버튼을 누르세요.", "#c0392b"),
            auth_btn.config(state="normal")
        ))
        auth_event.wait()
        root.after(0, lambda: (
            auth_btn.config(state="disabled"),
            set_status(f"[{label}] 수집 중입니다... 잠시만 기다려 주세요.", "#1452cc")
        ))

    def on_auth_done():
        auth_btn.config(state="disabled")
        auth_event.set()

    def worker():
        try:
            desk, out_root = prepare_out_root()
            total = run_collection(out_root)
            zip_path = zip_out_root(desk, out_root)
            root.after(0, lambda: finish_ok(zip_path, total))
        except Exception as e:
            root.after(0, lambda: finish_err(e))

    def finish_ok(zip_path, total):
        set_status("완료! 아래 zip 파일을 보내주세요.", "#1e8e3e")
        append("\n" + "=" * 50)
        append(f"완료. 바탕화면의 파일을 보내주세요:\n  {zip_path}")
        append(f"총 저장 하위페이지: {total}개")
        start_btn.config(state="normal", text="다시 실행")
        state["running"] = False
        try:
            # 결과 폴더를 탐색기로 열어줌
            os.startfile(os.path.dirname(zip_path))  # type: ignore[attr-defined]
        except Exception:
            pass
        messagebox.showinfo("완료",
                            f"바탕화면에 생성된\n'{DESKTOP_FOLDER_NAME}.zip'\n파일을 보내주세요.")

    def finish_err(e):
        set_status("오류가 발생했습니다.", "#c0392b")
        append(f"\n[오류] {e}")
        start_btn.config(state="normal", text="다시 시작")
        state["running"] = False
        messagebox.showerror(
            "오류",
            "크롬을 열 수 없거나 실행 중 문제가 발생했습니다.\n"
            "구글 크롬이 설치되어 있는지 확인 후 다시 시도해 주세요.\n\n"
            f"상세: {e}")

    def on_start():
        if state["running"]:
            return
        state["running"] = True
        box.delete("1.0", "end")
        start_btn.config(state="disabled", text="실행 중...")
        set_status("브라우저를 여는 중입니다...", "#1452cc")
        threading.Thread(target=worker, daemon=True).start()

    start_btn = tk.Button(btns, text="시작하기", command=on_start,
                          font=("맑은 고딕", 11, "bold"), bg="#1452cc", fg="white",
                          activebackground="#0d3aa0", activeforeground="white",
                          relief="flat", padx=20, pady=8)
    start_btn.pack(side="left")

    auth_btn = tk.Button(btns, text="인증 완료 - 다음 ▶", command=on_auth_done,
                         font=("맑은 고딕", 11, "bold"), bg="#1e8e3e", fg="white",
                         activebackground="#14672c", activeforeground="white",
                         relief="flat", padx=20, pady=8, state="disabled")
    auth_btn.pack(side="right")

    # 콜백을 전역에 연결
    LOG_SINK = gui_log
    WAIT_CB = gui_wait

    append("준비되었습니다. [시작하기] 를 눌러주세요.")

    # GUI 자기검증용: 창을 띄워 정상 구성됨을 확인한 뒤 자동 종료(실제 실행 아님).
    if os.environ.get("DIAG_GUITEST") == "1":
        root.update_idletasks()
        root.update()
        root.after(envint("DIAG_GUITEST_MS", 1500), root.destroy)

    root.mainloop()
    return 0


def main():
    if os.environ.get("DIAG_GUITEST") == "1":
        return run_gui()
    if AUTO:
        return run_headless()
    try:
        return run_gui()
    except Exception as e:
        # GUI 를 못 띄우는 환경이면 콘솔/헤드리스로 폴백
        log(f"[GUI 실행 불가, 일괄 모드로 전환] {e}")
        return run_headless()


if __name__ == "__main__":
    sys.exit(main())
