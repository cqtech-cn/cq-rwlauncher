"""末忆铁锈盒子公开 API 封装。

接口：https://www.rtsbox.cn/api/search_bbs.php
方法：POST form-data
参数：bbs_id (4=模组, 5=地图) / keyword / page
返回：{code, message, data:[{title, downurl, img, bbsurl}]}

⚠️ 实测发现：keyword 为空时，rtsbox.cn 不返回 JSON 而是返回
   "暂没有数据" 的 HTML 页面。本封装已对这种情况做兜底。
"""
from __future__ import annotations

import json
import html
import logging
import re
from typing import Any, Optional
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

API_URL = "https://www.rtsbox.cn/api/search_bbs.php"
BBS_ID_MOD = "4"
BBS_ID_MAP = "5"
DEFAULT_TIMEOUT = 15

# keyword 为空时使用的兜底关键词（rtsbox 对纯空查询返回 HTML）
_FALLBACK_KEYWORD = "%"


class _PostHTMLExtractor(HTMLParser):
    """提取帖子正文并输出受限 HTML，避免把原站页面脚本带入 WebView。"""

    _ALLOWED_TAGS = {
        "a", "b", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
        "h4", "hr", "i", "img", "li", "ol", "p", "pre", "s", "span", "strong",
        "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
    }
    _CANDIDATE_SCORES = {
        "jinsom-bbs-single-content": 140,
        "postmessage": 100,
        "post-content": 95,
        "thread-content": 90,
        "entry-content": 85,
        "article-content": 80,
        "t_f": 75,
        "pcb": 70,
        "article": 60,
        "content": 30,
        "detail": 20,
    }

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._capture_depth = 0
        self._ignored_depth = 0
        self._current: list[str] = []
        self._candidates: list[tuple[int, str]] = []
        self._current_score = 0
        self._void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def _candidate_score(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> int:
        values = " ".join(value or "" for name, value in attrs if name in ("id", "class")).lower()
        score = 0
        for token, token_score in self._CANDIDATE_SCORES.items():
            if token in values or (token == "article" and tag == "article") or (token == "body" and tag == "body"):
                score = max(score, token_score)
        return score

    def _attrs(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> str:
        safe: list[str] = []
        img_srcs: list[str] = []
        for name, value in attrs:
            name = name.lower()
            if name in ("class", "id", "alt", "title") and value:
                safe.append(f'{name}="{html.escape(value, quote=True)}"')
            elif name in ("href", "src") and value:
                absolute = urljoin(self._base_url, value)
                if urlparse(absolute).scheme in ("http", "https"):
                    safe.append(f'{name}="{html.escape(absolute, quote=True)}"')
                if tag == "img" and name == "src":
                    img_srcs.append(absolute)
        # 装饰性图片（分类图/作者头像/等级徽章/话题标签）打标，前端据此隐藏
        if tag == "img" and self._is_decoration_img(attrs, img_srcs):
            safe.append('data-ignore="1"')
        if tag == "a":
            # 不引导新窗口/外部浏览器，外链统一由前端拦截
            safe.append("rel=\"noopener noreferrer\"")
        return (" " + " ".join(safe)) if safe else ""

    @staticmethod
    def _is_decoration_img(attrs: list[tuple[str, Optional[str]]], srcs: list[str]) -> bool:
        """判断是否为装饰性图片：分类图 / 作者头像 / 等级徽章 / 话题标签等。"""
        classes = " ".join((v or "") for name, v in attrs if name.lower() == "class").lower()
        if "avatar" in classes or "opacity" in classes:
            return True
        for src in srcs:
            low = src.lower()
            if any(k in low for k in ("/lv/", "qlogo", "osswp", "/setting/", "wp-content")):
                return True
        return False

    def _append_start(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in self._ALLOWED_TAGS:
            self._current.append(f"<{tag}{self._attrs(tag, attrs)}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "template"):
            self._ignored_depth += 1
            return
        if self._ignored_depth > 0:
            return
        if self._capture_depth == 0:
            score = self._candidate_score(tag, attrs)
            if score:
                self._capture_depth = 1
                self._current = []
                self._current_score = score
                self._append_start(tag, attrs)
            return
        self._capture_depth += 1
        self._append_start(tag, attrs)
        if tag in self._void_tags:
            self._capture_depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if self._ignored_depth > 0:
            return
        if self._capture_depth > 0 and tag.lower() in self._ALLOWED_TAGS:
            self._current.append(f"<{tag}{self._attrs(tag, attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "template"):
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth > 0 or tag in self._void_tags:
            return
        if self._capture_depth == 0:
            return
        if tag in self._ALLOWED_TAGS:
            self._current.append(f"</{tag}>")
        self._capture_depth -= 1
        if self._capture_depth == 0:
            content = "".join(self._current).strip()
            if content:
                self._candidates.append((self._current_score, content))
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._capture_depth > 0 and self._ignored_depth == 0 and data.strip():
            self._current.append(html.escape(data.replace("\\n", "\n")))

    def result(self) -> str:
        if not self._candidates:
            return ""
        _, content = max(self._candidates, key=lambda item: (item[0], min(len(item[1]), 300000)))
        return content[:300000]


class RtsboxAPIError(Exception):
    """末忆铁锈盒子 API 错误（非致命：表示暂无数据）"""


class RtsboxAPI:
    """线程安全的轻量客户端。"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": "https://www.rtsbox.cn/",
            "Origin": "https://www.rtsbox.cn",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })

    def search(self, bbs_id: str, keyword: str = "", page: int = 1) -> list[dict[str, Any]]:
        """根据 bbs_id 搜索资源。

        Args:
            bbs_id: "4"=模组，"5"=地图
            keyword: 搜索关键词，可空（空值时自动用 % 通配）
            page: 页码，从 1 开始

        Returns:
            资源列表，每项含 title / downurl / img / bbsurl。
            任何错误都降级为返回空列表，不抛异常（前端不需要崩溃）。

        Raises:
            RtsboxAPIError: 不可恢复错误（极少触发）
        """
        # 兜底：keyword 为空时 rtsbox 返回 HTML 错误页
        kw = (keyword or "").strip() or _FALLBACK_KEYWORD

        logger.debug("搜索 bbs_id=%s keyword=%r page=%s", bbs_id, kw, page)
        try:
            resp = self._session.post(
                API_URL,
                data={"bbs_id": bbs_id, "keyword": kw, "page": str(page)},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.warning("rtsbox 网络请求失败：%s", e)
            raise RtsboxAPIError(f"网络请求失败：{e}") from e

        text = resp.text or ""
        # 关键修复：rtsbox 在无结果时返回 HTML 而非 JSON
        if not text.lstrip().startswith(("{", "[")):
            # 可能是 "暂没有数据" HTML 页面，视为空结果
            logger.debug("rtsbox 返回非 JSON（空结果页），已降级为空列表")
            return []

        try:
            payload = json.loads(text)
        except ValueError:
            # 仍然不是合法 JSON，截取前 200 字符用于诊断
            snippet = text[:200].replace("\n", " ")
            raise RtsboxAPIError(f"响应不是合法 JSON：{snippet}") from None

        if not isinstance(payload, dict):
            return []

        code = payload.get("code")
        if code != 200:
            raise RtsboxAPIError(
                f"API 返回错误：code={code} message={payload.get('message')}"
            )

        data = payload.get("data")
        return data if isinstance(data, list) else []

    def search_mods(self, keyword: str = "", page: int = 1) -> list[dict[str, Any]]:
        return self.search(BBS_ID_MOD, keyword, page)

    def search_maps(self, keyword: str = "", page: int = 1) -> list[dict[str, Any]]:
        return self.search(BBS_ID_MAP, keyword, page)

    def fetch_post(self, url: str) -> str:
        """获取原帖并提取正文为可安全嵌入的 HTML。"""
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RtsboxAPIError("原贴地址无效")
        try:
            resp = self._session.get(url, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RtsboxAPIError(f"原贴加载失败：{e}") from e
        parser = _PostHTMLExtractor(resp.url or url)
        parser.feed(resp.text or "")
        content = parser.result()
        if not content:
            raise RtsboxAPIError("未找到原贴正文")
        return content

