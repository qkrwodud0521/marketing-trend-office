"""리포트 JSON을 검증하고 HTML로 렌더링한다."""
import datetime as dt
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES = ("daily", "weekly", "monthly", "quarterly")
NAMES = {"daily": "데일리", "weekly": "위클리", "monthly": "먼슬리", "quarterly": "분기"}


def validate(path):
    """문제 목록을 돌려준다. 비어 있으면 통과."""
    if not path.exists():
        return [f"{path.name} 파일이 저장되지 않았습니다"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"JSON 문법 오류: {e}"]
    errors = []
    for key in ("headline", "summary", "sections"):
        if not doc.get(key):
            errors.append(f"'{key}' 필드가 비어 있습니다")
    items = 0
    for s in doc.get("sections", []):
        for it in s.get("items", []):
            items += 1
            title = it.get("title", "(제목 없음)")
            urls = [src.get("url", "") for src in it.get("sources", [])]
            if not any(u.startswith("http") for u in urls):
                errors.append(f"'{title}' 항목에 출처 URL이 없습니다")
            for key in ("title", "body", "why", "action"):
                if not it.get(key):
                    errors.append(f"'{title}' 항목의 '{key}'가 비어 있습니다")
    if items < 3:
        errors.append(f"항목이 {items}개뿐입니다 (최소 3개)")
    quiz = doc.get("quiz") or []
    if len(quiz) < 2:
        errors.append("'quiz'에 문제가 2개 이상 있어야 합니다")
    for i, q in enumerate(quiz, 1):
        opts = q.get("options") or []
        ans = q.get("answer")
        if not q.get("q") or len(opts) < 3:
            errors.append(f"퀴즈 {i}번에 문제나 보기(3개 이상)가 없습니다")
        elif not isinstance(ans, int) or not 0 <= ans < len(opts):
            errors.append(f"퀴즈 {i}번의 answer가 보기 번호(0~{len(opts) - 1})가 아닙니다")
    return errors


def e(text):
    return escape(str(text or ""))


def html_page(title, body, css_path):
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="{css_path}">
</head>
<body>
{body}
</body>
</html>
"""


def render_item(it):
    parts = ['<article class="card">', '<div class="card-meta">']
    if it.get("rank"):
        parts.append(f'<span class="rank">{e(it["rank"])}</span>')
    if it.get("tag"):
        parts.append(f'<span class="tag">{e(it["tag"])}</span>')
    if it.get("brand"):
        parts.append(f'<span class="brand">{e(it["brand"])}</span>')
    parts.append("</div>")
    parts.append(f'<h3>{e(it.get("title"))}</h3>')
    parts.append(f'<p class="body">{e(it.get("body"))}</p>')
    if it.get("points"):
        parts.append('<ul class="points">' + "".join(f"<li>{e(p)}</li>" for p in it["points"]) + "</ul>")
    if it.get("why"):
        parts.append(f'<div class="note why"><b>왜 주목할까</b><p>{e(it["why"])}</p></div>')
    if it.get("action"):
        parts.append(f'<div class="note action"><b>팔로업</b><p>{e(it["action"])}</p></div>')
    if it.get("keywords"):
        parts.append('<div class="kw small">' + "".join(f"<span>#{e(k)}</span>" for k in it["keywords"]) + "</div>")
    srcs = [s for s in it.get("sources", []) if str(s.get("url", "")).startswith("http")]
    if srcs:
        links = []
        for s in srcs:
            date = f' <time>{e(s["date"])}</time>' if s.get("date") else ""
            links.append(f'<li><a href="{e(s["url"])}" target="_blank" rel="noopener">{e(s.get("name") or s["url"])}</a>{date}</li>')
        parts.append('<ul class="sources">' + "".join(links) + "</ul>")
    parts.append("</article>")
    return "\n".join(parts)


def neighbours(kind, pid):
    ids = sorted(p.stem for p in (ROOT / "data" / kind).glob("*.json"))
    if pid not in ids:
        return None, None
    i = ids.index(pid)
    return (ids[i - 1] if i > 0 else None), (ids[i + 1] if i + 1 < len(ids) else None)


def render_file(json_path):
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    kind = json_path.parent.name
    pid = json_path.stem
    made = dt.datetime.fromtimestamp(json_path.stat().st_mtime)
    prev_id, next_id = neighbours(kind, pid)

    nav = ['<nav class="top"><a href="../../list.html">← 전체 리포트</a><span>']
    if prev_id:
        nav.append(f'<a href="{e(prev_id)}.html">이전</a>')
    if next_id:
        nav.append(f'<a href="{e(next_id)}.html">다음</a>')
    nav.append("</span></nav>")

    edition = " · 주말판" if doc.get("edition") == "weekend" else ""
    body = ['<main class="wrap">', "".join(nav), '<header class="hero">',
            f'<span class="badge {kind}">{NAMES[kind]} 리포트{edition}</span>',
            f'<p class="period">{e(doc.get("period_label") or pid)}</p>',
            f'<h1>{e(doc.get("headline"))}</h1>',
            f'<p class="made">{made:%Y-%m-%d %H:%M} 생성</p>', "</header>"]

    if doc.get("summary"):
        body.append('<section class="summary"><h2>3줄 요약</h2><ol>'
                    + "".join(f"<li>{e(s)}</li>" for s in doc["summary"]) + "</ol></section>")
    if doc.get("keywords"):
        body.append('<div class="kw">' + "".join(f"<span>#{e(k)}</span>" for k in doc["keywords"]) + "</div>")

    for s in doc.get("sections", []):
        body.append(f'<section class="block"><h2>{e(s.get("title"))}</h2>')
        if s.get("description"):
            body.append(f'<p class="desc">{e(s["description"])}</p>')
        body.append('<div class="cards">' + "\n".join(render_item(it) for it in s.get("items", [])) + "</div></section>")

    if doc.get("follow_up"):
        body.append('<section class="summary follow"><h2>다음에 지켜볼 것</h2><ul>'
                    + "".join(f"<li>{e(f)}</li>" for f in doc["follow_up"]) + "</ul></section>")
    if doc.get("quiz"):
        qs = []
        for i, q in enumerate(doc["quiz"], 1):
            opts = "".join(f"<li>{e(o)}</li>" for o in q.get("options", []))
            ans = q.get("answer")
            right = q["options"][ans] if isinstance(ans, int) and 0 <= ans < len(q.get("options", [])) else ""
            qs.append(f'<div class="quiz"><p class="q">Q{i}. {e(q.get("q"))}</p><ol>{opts}</ol>'
                      f'<details><summary>정답 보기</summary><p><b>{e(right)}</b> — {e(q.get("explain"))}</p></details></div>')
        body.append('<section class="summary follow"><h2>확인 퀴즈</h2>' + "".join(qs) + "</section>")
    body.append('<footer>출처 링크를 눌러 원문을 꼭 확인하세요. 이 리포트는 AI가 웹 자료를 조사해 자동으로 작성했습니다.</footer></main>')

    out = ROOT / "reports" / kind / f"{pid}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    title = f"{NAMES[kind]} 마케팅 트렌드 · {doc.get('period_label') or pid}"
    out.write_text(html_page(title, "\n".join(body), "../../assets/style.css"), encoding="utf-8")
    return out


def write_game_data():
    """office.html이 file://에서도 읽을 수 있도록 모든 리포트를 JS 파일 하나로 묶는다."""
    data = {"version": dt.datetime.now().isoformat(timespec="seconds"), "reports": {}}
    for kind in TYPES:
        rows = []
        for p in sorted((ROOT / "data" / kind).glob("*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            made = dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
            rows.append({"id": p.stem, "generatedAt": made, "html": f"reports/{kind}/{p.stem}.html", "doc": doc})
        data["reports"][kind] = rows
    js = "window.REPORT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n"
    (ROOT / "assets" / "reports-data.js").write_text(js, encoding="utf-8")


def build_index():
    write_game_data()
    cols = []
    latest = None
    for kind in TYPES:
        rows = []
        for p in sorted((ROOT / "data" / kind).glob("*.json"), reverse=True):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if kind == "daily" and latest is None:
                latest = (p.stem, doc)
            rows.append(f'<li><a href="reports/{kind}/{e(p.stem)}.html">'
                        f'<span class="period">{e(doc.get("period_label") or p.stem)}</span>'
                        f'<span class="hl">{e(doc.get("headline"))}</span></a></li>')
        empty = '<li class="empty">아직 리포트가 없어요</li>'
        cols.append(f'<section class="col"><h2><span class="badge {kind}">{NAMES[kind]}</span></h2>'
                    f'<ul class="list">{"".join(rows) or empty}</ul></section>')

    hero = ""
    if latest:
        pid, doc = latest
        hero = (f'<a class="latest" href="reports/daily/{e(pid)}.html"><span class="badge daily">오늘의 리포트</span>'
                f'<p class="period">{e(doc.get("period_label"))}</p><h2>{e(doc.get("headline"))}</h2>'
                + ('<ol>' + "".join(f"<li>{e(s)}</li>" for s in doc.get("summary", [])) + "</ol>" if doc.get("summary") else "")
                + "<span class=\"more\">리포트 보기 →</span></a>")

    body = ('<main class="wrap wide"><header class="hero index"><h1>마케팅 트렌드 리포트</h1>'
            '<p class="made">매일 아침 9시, 마케터가 알아야 할 아이디어와 밈을 정리합니다. '
            '<a href="office.html">🏢 오피스로 가기 →</a></p></header>'
            f'{hero}<div class="grid">{"".join(cols)}</div></main>')
    (ROOT / "list.html").write_text(html_page("마케팅 트렌드 리포트", body, "assets/style.css"), encoding="utf-8")
    # 사이트 첫 주소(…/marketing-trend-office/)로 들어와도 오피스가 열리게 한다
    (ROOT / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>마케팅팀 오피스</title>'
        '<meta http-equiv="refresh" content="0; url=office.html">'
        '<script>location.replace("office.html" + location.search + location.hash)</script>'
        '<a href="office.html">🏢 오피스로 가기</a>\n', encoding="utf-8")
