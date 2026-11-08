"""节日主题：按法定节假日自动切换点缀配色。

数据来源优先级（逐级降级，任何一级失败都不会影响启动器正常运行）：
1. 联网同步：向配置的节假日接口拉取当年放假安排
2. 本地缓存：最近一次成功同步的结果，默认保留 30 天
3. 内置兜底表：随启动器版本更新，断网时也能正确切换

只识别法定假期，普通周末与调休补班不触发主题。
"""
from __future__ import annotations

import datetime
import json
import logging
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 节日主题标识 → 展示名（配色在 frontend/src/styles/global.css 中定义）
FESTIVAL_NAMES: dict[str, str] = {
    "new-year": "元旦",
    "spring-festival": "春节",
    "qingming": "清明节",
    "labour-day": "劳动节",
    "dragon-boat": "端午节",
    "mid-autumn": "中秋节",
    "national-day": "国庆节",
}

# 节假日接口里的名称关键字 → 主题标识（先匹配先得，国庆节、中秋节合并放假时算国庆）
_NAME_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("元旦", "new-year"),
    ("春节", "spring-festival"),
    ("除夕", "spring-festival"),
    ("清明", "qingming"),
    ("劳动", "labour-day"),
    ("国庆", "national-day"),
    ("中秋", "mid-autumn"),
    ("端午", "dragon-boat"),
)

# 内置兜底表：{年份: [(开始日期, 结束日期, 主题标识)]}
# 数据为参考区间，联网同步成功时以接口结果为准
_BUILTIN: dict[int, tuple[tuple[str, str, str], ...]] = {
    2025: (
        ("2025-01-01", "2025-01-01", "new-year"),
        ("2025-01-28", "2025-02-04", "spring-festival"),
        ("2025-04-04", "2025-04-06", "qingming"),
        ("2025-05-01", "2025-05-05", "labour-day"),
        ("2025-05-31", "2025-06-02", "dragon-boat"),
        ("2025-10-01", "2025-10-08", "national-day"),
    ),
    2026: (
        ("2026-01-01", "2026-01-03", "new-year"),
        ("2026-02-15", "2026-02-22", "spring-festival"),
        ("2026-04-04", "2026-04-06", "qingming"),
        ("2026-05-01", "2026-05-05", "labour-day"),
        ("2026-06-19", "2026-06-21", "dragon-boat"),
        ("2026-09-25", "2026-09-27", "mid-autumn"),
        ("2026-10-01", "2026-10-08", "national-day"),
    ),
    2027: (
        ("2027-01-01", "2027-01-03", "new-year"),
        ("2027-02-06", "2027-02-12", "spring-festival"),
        ("2027-04-04", "2027-04-06", "qingming"),
        ("2027-05-01", "2027-05-05", "labour-day"),
        ("2027-06-09", "2027-06-11", "dragon-boat"),
        ("2027-09-15", "2027-09-17", "mid-autumn"),
        ("2027-10-01", "2027-10-07", "national-day"),
    ),
}

# 表外年份的安全兜底：只认固定公历日期的假期，避免给出错误区间
_FIXED_RULES: tuple[tuple[str, str, str], ...] = (
    ("01-01", "01-01", "new-year"),
    ("05-01", "05-05", "labour-day"),
    ("10-01", "10-07", "national-day"),
)

CACHE_VERSION = 1


def _parse_date(s: str) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def theme_from_name(name: str) -> Optional[str]:
    """按假期名称推断主题标识。"""
    text = str(name or "")
    for keyword, theme in _NAME_KEYWORDS:
        if keyword in text:
            return theme
    return None


def _ranges_from_days(days: list[tuple[datetime.date, str]]) -> list[list[str]]:
    """把逐日数据按主题合并成连续区间，返回 [[开始, 结束, 主题], ...]。"""
    days = sorted({(d, t) for d, t in days if t})
    merged: list[list[str]] = []
    for day, theme in days:
        if merged and merged[-1][2] == theme:
            last_end = _parse_date(merged[-1][1])
            if last_end and (day - last_end).days <= 1:
                merged[-1][1] = day.isoformat()
                continue
        merged.append([day.isoformat(), day.isoformat(), theme])
    return merged


def parse_online(payload: Any) -> list[list[str]]:
    """解析节假日接口返回，得到区间列表。

    兼容 timor.tech 风格：{"holiday": {"01-01": {"holiday": true, "name": "元旦", "date": "2026-01-01"}}}
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("holiday") or payload.get("data") or payload.get("days") or {}
    if not isinstance(raw, dict):
        return []
    days: list[tuple[datetime.date, str]] = []
    for item in raw.values():
        if not isinstance(item, dict):
            continue
        # 只认放假（holiday 为真），补班日 holiday 为 False，直接跳过
        if item.get("holiday") is False or item.get("workday") is True:
            continue
        day = _parse_date(item.get("date") or "")
        theme = theme_from_name(item.get("name") or "")
        if day and theme:
            days.append((day, theme))
    return _ranges_from_days(days)


def _builtin_ranges(year: int) -> list[list[str]]:
    """内置兜底表：优先用年度表，表外年份退化为固定日期规则。"""
    table = _BUILTIN.get(year)
    if table:
        return [[a, b, t] for a, b, t in table]
    prefix = f"{year}-"
    return [[prefix + a, prefix + b, t] for a, b, t in _FIXED_RULES]


def _load_cache(cache_path: Optional[Path], max_age_days: int) -> Optional[list[list[str]]]:
    if not cache_path or not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != CACHE_VERSION:
            return None
        synced = _parse_date(data.get("synced_at") or "")
        if not synced:
            return None
        if (datetime.date.today() - synced).days > max_age_days:
            return None
        ranges = data.get("ranges")
        if isinstance(ranges, list) and ranges:
            return ranges
    except (OSError, ValueError, TypeError) as e:
        logger.debug("节日缓存读取失败：%s", e)
    return None


def _save_cache(cache_path: Optional[Path], ranges: list[list[str]]) -> None:
    if not cache_path or not ranges:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "synced_at": datetime.date.today().isoformat(),
                    "ranges": ranges,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.debug("节日缓存写入失败：%s", e)


def _fetch_online(api_url: str, timeout: float, year: int) -> Optional[list[list[str]]]:
    """联网拉取当年放假安排；失败返回 None。"""
    if not api_url:
        return None
    url = str(api_url).replace("{year}", str(year))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CQRWLauncher"})
        with urllib.request.urlopen(req, timeout=float(timeout or 5)) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        logger.info("节日数据联网同步失败，改用本地缓存或内置表：%s", e)
        return None
    ranges = parse_online(payload)
    return ranges or None


def detect(
    api_url: str = "",
    timeout: float = 5,
    cache_path: Optional[Path] = None,
    cache_max_age_days: int = 30,
    today: Optional[datetime.date] = None,
) -> dict:
    """返回今日节日主题状态。

    结果字段：active / theme / name / date / period / source
    source 取值：online（联网同步）/ cache（本地缓存）/ builtin（内置兜底）
    """
    day = today or datetime.date.today()
    ranges: Optional[list[list[str]]] = None
    source = "builtin"

    ranges = _fetch_online(api_url, timeout, day.year)
    if ranges:
        source = "online"
        _save_cache(cache_path, ranges)
    else:
        ranges = _load_cache(cache_path, cache_max_age_days)
        if ranges:
            source = "cache"
        else:
            ranges = _builtin_ranges(day.year)

    for start_s, end_s, theme in ranges:
        start = _parse_date(start_s)
        end = _parse_date(end_s)
        if not start or not end:
            continue
        if start <= day <= end:
            return {
                "ok": True,
                "active": True,
                "theme": theme,
                "name": FESTIVAL_NAMES.get(theme, theme),
                "date": day.isoformat(),
                "period": f"{start.isoformat()} ~ {end.isoformat()}",
                "source": source,
            }
    return {
        "ok": True,
        "active": False,
        "theme": "",
        "name": "",
        "date": day.isoformat(),
        "period": "",
        "source": source,
    }