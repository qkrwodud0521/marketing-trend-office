#!/usr/bin/env python3
"""마케팅 트렌드 및 최신 기사 크롤러.

외부 라이브러리 설치 없이 Python 표준 라이브러리(urllib, xml, html.parser)만으로 동작합니다.
Claude가 웹 검색을 수십 번 돌면서 토큰을 낭비하지 않도록,
파이썬이 먼저 무료로 최신 뉴스/아티클 원문을 수집하여 에이전트에게 1회에 전달합니다.
"""

import datetime as dt
import html
from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class SimpleHTMLTextExtractor(HTMLParser):
    """HTML 태그를 제거하고 깨끗한 텍스트만 추출"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.text_parts = []

    def handle_data(self, data):
        cleaned = data.strip()
        if cleaned:
            self.text_parts.append(cleaned)

    def get_text(self):
        return " ".join(self.text_parts)


def clean_html(raw_html):
    if not raw_html:
        return ""
    # script, style 태그 내용 제거
    cleaned = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw_html, flags=re.DOTALL | re.IGNORECASE)
    parser = SimpleHTMLTextExtractor()
    try:
        parser.feed(cleaned)
        text = parser.get_text()
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', cleaned)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def fetch_url(url, timeout=7):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw = resp.read()
            try:
                return raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                return raw.decode("utf-8", errors="replace")
    except Exception as e:
        return None


def parse_rss_feed(source_name, url, max_items=8):
    xml_data = fetch_url(url)
    if not xml_data:
        return []

    articles = []
    try:
        root = ET.fromstring(xml_data)
        # RSS 2.0: <rss><channel><item>
        # Atom: <feed><entry>
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for it in items[:max_items]:
            title_node = it.find("title") or it.find("{http://www.w3.org/2005/Atom}title")
            link_node = it.find("link") or it.find("{http://www.w3.org/2005/Atom}link")
            desc_node = it.find("description") or it.find("{http://www.w3.org/2005/Atom}summary") or it.find("{http://www.w3.org/2005/Atom}content")
            pub_date_node = it.find("pubDate") or it.find("{http://www.w3.org/2005/Atom}published") or it.find("{http://www.w3.org/2005/Atom}updated")

            title = clean_html(title_node.text) if title_node is not None and title_node.text else ""
            if link_node is not None:
                link = link_node.text if link_node.text else link_node.attrib.get("href", "")
            else:
                link = ""
            desc = clean_html(desc_node.text) if desc_node is not None and desc_node.text else ""
            pub_date = pub_date_node.text.strip() if pub_date_node is not None and pub_date_node.text else ""

            if title and link:
                articles.append({
                    "source": source_name,
                    "title": title,
                    "link": link.strip(),
                    "date": pub_date,
                    "summary": desc[:300] if desc else ""
                })
    except Exception as e:
        pass
    return articles


def get_google_news_rss(query, max_items=10):
    encoded_q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl=ko&gl=KR&ceid=KR:ko"
    return parse_rss_feed("구글뉴스 (" + query + ")", url, max_items=max_items)


def collect_latest_sources(limit=25):
    """주요 마케팅 소스 및 뉴스 피드에서 최신 기사 수집"""
    feeds = [
        # 마케팅/트렌드 전문 매체 RSS
        ("매드타임스", "https://www.madtimes.org/rss/allArticle.xml"),
        ("더피알", "https://www.the-pr.co.kr/rss/allArticle.xml"),
        ("고구마팜", "https://gogumafarm.kr/feed/"),
        ("브랜드브리프", "https://www.brandbrief.co.kr/rss/allArticle.xml"),
        # 키워드별 구글 뉴스 RSS (실시간 최신 트렌드/캠페인/팝업/밈 포착)
        ("구글뉴스_마케팅", "https://news.google.com/rss/search?q=%EB%A7%88%EC%BC%80%ED%8C%85+%EC%BA%A0%ED%8E%98%EC%9D%B8+when%3A3d&hl=ko&gl=KR&ceid=KR:ko"),
        ("구글뉴스_팝업콜라보", "https://news.google.com/rss/search?q=%ED%8C%9D%EC%97%85%EC%8A%A4%ED%86%A0%EC%96%B4+%EC%BD%9C%EB%9D%BC%EB%B3%B4+when%3A3d&hl=ko&gl=KR&ceid=KR:ko"),
        ("구글뉴스_트렌드밈", "https://news.google.com/rss/search?q=%EB%A7%88%EC%BC%80%ED%8C%85+%EB%B0%88+%EC%B1%8C%EB%A6%B0%EC%A7%80+when%3A7d&hl=ko&gl=KR&ceid=KR:ko"),
    ]

    all_articles = []
    seen_titles = set()

    for name, url in feeds:
        items = parse_rss_feed(name, url, max_items=6)
        for it in items:
            normalized_title = re.sub(r'[\s\W]+', '', it["title"])
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            all_articles.append(it)
            if len(all_articles) >= limit:
                break
        if len(all_articles) >= limit:
            break

    return all_articles


def format_scraped_articles_markdown(articles):
    if not articles:
        return "(수집된 외부 기사가 없습니다. 필요 시 웹 검색을 통해 최신 사례를 보충하세요.)"

    lines = ["## 사전 수집된 최신 마케팅 기사 및 트렌드 소스 원문\n"]
    lines.append("아래 기사들은 파이썬 크롤러가 사전에 수집한 최신 데이터입니다. 이 내용을 우선 활용하여 보고서를 작성하세요.\n")
    for i, it in enumerate(articles, 1):
        lines.append(f"### [{i}] {it['title']}")
        lines.append(f"- 출처: {it['source']}")
        lines.append(f"- 링크: {it['link']}")
        if it.get("date"):
            lines.append(f"- 발행일: {it['date']}")
        if it.get("summary"):
            lines.append(f"- 내용 요약: {it['summary']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    articles = collect_latest_sources(limit=10)
    print(f"수집된 기사 수: {len(articles)}")
    if articles:
        print(format_scraped_articles_markdown(articles[:3]))

