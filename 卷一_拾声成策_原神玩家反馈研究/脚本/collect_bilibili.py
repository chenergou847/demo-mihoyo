#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
作品集 A · B站玩家反馈采集器 v2（公开接口、无登录可用、只读）

实测结论（2026-10-06 本机验证）：
  - 首页拿 buvid3/b_nut cookie 后，`search/type` 与 `reply` 才不返回 412。
  - `view` 接口必须走 wbi 签名版 `/x/web-interface/wbi/view`，否则 412。
  - **匿名访问下评论区被限制为「每条视频约 3 条热门评论」**（`cursor.is_end=True`
    而 `all_count` 仍为数千）。因此取数策略是**铺量**：多关键词 × 多视频 × 少量热门评论。
  - 若提供**已登录**的 Netscape cookie 文件（--cookie-file），会尝试全量翻页。

输出：
  - 反馈原始表 CSV：平台, 来源视频, 用户编号, 内容, 链接, 日期, 点赞数
  - 采集日志 JSON：视频清单（播放/评论/点赞）、统计、失败原因码、**已声明的样本局限**

纪律：
  - 抓不到记 null + 原因码，不估算、不编造。
  - 用户编号为稳定匿名映射；**不落盘昵称与 mid**。
  - 请求间加延时，不做高并发。

用法：
  python collect_bilibili.py --keywords "幽境危战,原神7.1" --pages 2 --max-videos 60 \
      --out "原始数据/bilibili_raw_20261006.csv"
  python collect_bilibili.py --keywords "..." --cookie-file "cookies.txt" --full-paging --out ...
"""
from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import http.cookiejar
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CST = timezone(timedelta(hours=8))
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))
_stats = {"requests": 0, "ok": 0, "failed": 0, "comments_raw": 0, "comments_kept": 0,
          "dropped_short": 0, "dropped_out_of_window": 0}
_errors: list[dict] = []
_endpoints_used: dict[str, int] = {}


# ----------------------------------------------------------------------------- HTTP
def _get(url: str, referer: str = "https://www.bilibili.com/", retries: int = 3) -> bytes | None:
    delay = 1.2
    for attempt in range(1, retries + 1):
        _stats["requests"] += 1
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": referer,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            body = _opener.open(req, timeout=25).read()
            _stats["ok"] += 1
            time.sleep(delay + random.uniform(0, 0.4))
            return body
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None) or type(exc).__name__
            _errors.append({"url": url[:160], "attempt": attempt, "reason_code": str(code)})
            if attempt == retries:
                _stats["failed"] += 1
                return None
            time.sleep(delay * attempt * 1.5)
    return None


def _json(url: str, referer: str = "https://www.bilibili.com/") -> dict | None:
    body = _get(url, referer=referer)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        _errors.append({"url": url[:160], "reason_code": "JSON_PARSE:%s" % type(exc).__name__})
        return None


# ----------------------------------------------------------------------------- WBI
@functools.lru_cache(maxsize=1)
def _mixin_key() -> str:
    nav = _json("https://api.bilibili.com/x/web-interface/nav") or {}
    wbi = ((nav.get("data") or {}).get("wbi_img")) or {}
    img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    raw = img + sub
    if len(raw) < 64:
        return ""
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def wbi_sign(params: dict) -> str:
    mixin = _mixin_key()
    params = dict(params)
    params["wts"] = int(time.time())
    query = urllib.parse.urlencode(sorted((k, str(v)) for k, v in params.items()))
    params["w_rid"] = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
    return urllib.parse.urlencode(sorted(params.items()))


def bootstrap(cookie_file: str | None) -> None:
    print("[1/4] 获取风控 cookie ...")
    _get("https://www.bilibili.com/", referer="https://www.bilibili.com/")
    names = sorted(c.name for c in _cj)
    print("      会话 cookie = %s" % names)
    if cookie_file and os.path.exists(cookie_file):
        loaded = http.cookiejar.MozillaCookieJar(cookie_file)
        try:
            loaded.load(ignore_discard=True, ignore_expires=True)
            n = 0
            for c in loaded:
                _cj.set_cookie(c)
                n += 1
            print("      已加载登录 cookie %d 条（启用全量翻页）" % n)
        except Exception as exc:  # noqa: BLE001
            print("      ⚠ cookie 文件解析失败：%s" % exc)
    elif cookie_file:
        print("      ⚠ cookie 文件不存在：%s（继续匿名模式）" % cookie_file)


# ----------------------------------------------------------------------------- 采集
def search_videos(keyword: str, pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        url = ("https://api.bilibili.com/x/web-interface/search/type?"
               + urllib.parse.urlencode({"search_type": "video", "keyword": keyword, "page": page}))
        data = _json(url, referer="https://search.bilibili.com/")
        if not data or data.get("code") != 0:
            _errors.append({"stage": "search", "keyword": keyword, "page": page,
                            "reason_code": "API_CODE_%s" % (data or {}).get("code")})
            continue
        for item in (data.get("data") or {}).get("result") or []:
            if item.get("type") != "video" or not item.get("bvid"):
                continue
            out.append({
                "keyword": keyword,
                "aid": item.get("aid"),
                "bvid": item.get("bvid"),
                "title": re.sub(r"</?em[^>]*>", "", item.get("title") or ""),
                "author": item.get("author"),
                "play": item.get("play"),
                "review_count": item.get("review"),
                "like": item.get("like"),
                "danmaku": item.get("danmaku"),
                "pubdate": item.get("pubdate"),
                "tags": item.get("tag"),
            })
    return out


def video_stat(aid: int) -> dict:
    """wbi 版 view：拿播放/点赞/评论/弹幕/发布时间的权威值。"""
    data = _json("https://api.bilibili.com/x/web-interface/wbi/view?" + wbi_sign({"aid": aid}))
    if not data or data.get("code") != 0:
        _errors.append({"stage": "view-wbi", "aid": aid, "reason_code": "API_CODE_%s" % (data or {}).get("code")})
        return {}
    d = data.get("data") or {}
    st = d.get("stat") or {}
    return {"title": d.get("title"), "author": (d.get("owner") or {}).get("name"),
            "play": st.get("view"), "like": st.get("like"), "review_count": st.get("reply"),
            "danmaku": st.get("danmaku"), "pubdate": d.get("pubdate")}


def _pack(rep: dict, bvid: str, keyword: str) -> dict:
    msg = re.sub(r"\s+", " ", ((rep.get("content") or {}).get("message") or "")).strip()
    return {
        "平台": "B站",
        "来源视频": bvid,
        "关键词": keyword,
        "用户编号": "",
        "_mid": str(rep.get("mid") or ""),
        "内容": msg,
        "链接": "https://www.bilibili.com/video/%s#reply%s" % (bvid, rep.get("rpid_str") or rep.get("rpid")),
        "日期": datetime.fromtimestamp(int(rep.get("ctime") or 0), CST).strftime("%Y-%m-%d"),
        "点赞数": rep.get("like"),
    }


def fetch_comments(aid: int, bvid: str, keyword: str, target: int, min_len: int,
                   full_paging: bool, since_ts: int = 0) -> list[dict]:
    """优先 wbi/main；匿名下每条视频仅约 3 条热门评论，故一次请求即可。"""
    rows: list[dict] = []
    nxt, page, mode = 0, 1, 3
    max_pages = 30 if full_paging else 1
    while len(rows) < target and page <= max_pages:
        url = ("https://api.bilibili.com/x/v2/reply/wbi/main?"
               + wbi_sign({"oid": aid, "type": 1, "mode": mode, "ps": 20,
                           "next": nxt, "plat": 1, "web_location": 1315875}))
        data = _json(url)
        if not data or data.get("code") != 0:
            _errors.append({"stage": "reply-wbi", "aid": aid, "page": page,
                            "reason_code": "API_CODE_%s" % (data or {}).get("code")})
            break
        _endpoints_used["reply/wbi/main"] = _endpoints_used.get("reply/wbi/main", 0) + 1
        d = data.get("data") or {}
        replies = d.get("replies") or []
        cur = d.get("cursor") or {}
        for rep in replies:
            _stats["comments_raw"] += 1
            packed = _pack(rep, bvid, keyword)
            if len(packed["内容"]) < min_len:
                _stats["dropped_short"] += 1
                continue
            ctime = int(rep.get("ctime") or 0)
            if since_ts and ctime < since_ts:
                _stats["dropped_out_of_window"] += 1
                continue
            rows.append(packed)
            if len(rows) >= target:
                break
        if cur.get("is_end") or not cur.get("next"):
            break
        nxt = cur.get("next")
        page += 1
    return rows


def anonymize(rows: list[dict]) -> int:
    mapping: dict[str, str] = {}
    for r in rows:
        mid = r.pop("_mid", "") or ""
        if not mid:
            r["用户编号"] = "U_UNKNOWN"
            continue
        if mid not in mapping:
            mapping[mid] = "U%04d" % (len(mapping) + 1)
        r["用户编号"] = mapping[mid]
    return len(mapping)


# ----------------------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True, help="逗号分隔")
    ap.add_argument("--pages", type=int, default=1, help="每个关键词搜索页数（每页约 20 条）")
    ap.add_argument("--max-videos", type=int, default=60, help="按评论数排序后取前 N 个视频")
    ap.add_argument("--comments-per-video", type=int, default=20, help="目标条数（匿名下实际≈3）")
    ap.add_argument("--min-len", type=int, default=6)
    ap.add_argument("--since", default=None,
                    help="评论日期下限 YYYY-MM-DD（口径窗口；早于此的评论被排除并计数）")
    ap.add_argument("--cookie-file", default=None, help="Netscape 格式 cookie 文件（可选，登录后可全量翻页）")
    ap.add_argument("--full-paging", action="store_true", help="配合 cookie 全量翻页")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    since_ts = 0
    if args.since:
        since_ts = int(datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=CST).timestamp())
        print("口径窗口：仅保留 %s 及之后的评论（更早评论排除并计数）" % args.since)
    bootstrap(args.cookie_file)

    print("[2/4] 搜索视频 ...")
    seen, videos = set(), []
    for kw in keywords:
        got = search_videos(kw, args.pages)
        print("      %-22s 命中 %d 条" % (kw, len(got)))
        for v in got:
            if v["bvid"] in seen:
                continue
            seen.add(v["bvid"])
            videos.append(v)
    videos.sort(key=lambda v: (v.get("review_count") or 0), reverse=True)
    videos = videos[:args.max_videos]
    print("      去重后 %d 个视频，按评论数取前 %d 个" % (len(seen), len(videos)))

    print("[3/4] 拉取评论 ...")
    rows: list[dict] = []
    for i, v in enumerate(videos, 1):
        st = video_stat(int(v["aid"]))
        if st:
            v.update({k: st.get(k, v.get(k)) for k in ("title", "author", "play", "like",
                                                       "review_count", "danmaku", "pubdate")})
        got = fetch_comments(int(v["aid"]), v["bvid"], v["keyword"],
                             args.comments_per_video, args.min_len, args.full_paging, since_ts)
        v["采取评论数"] = len(got)
        rows.extend(got)
        if i % 10 == 0 or i == len(videos):
            print("      (%d/%d) 累计评论 %d" % (i, len(videos), len(rows)))

    users = anonymize(rows)

    print("[4/4] 落盘 ...")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cols = ["平台", "来源视频", "关键词", "用户编号", "内容", "链接", "日期", "点赞数"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    log = {
        "collected_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S%z"),
        "keywords": keywords,
        "window_since": args.since,
        "videos": [{k: v.get(k) for k in ("keyword", "bvid", "aid", "title", "author", "play",
                                          "review_count", "like", "danmaku", "pubdate",
                                          "tags", "采取评论数")} for v in videos],
        "stats": dict(_stats, comments_kept=len(rows), unique_users=users),
        "endpoints_used": _endpoints_used,
        "errors": _errors[:200],
        "declared_limitations": [
            "匿名访问下 B站评论区被限制为约 3 条热门评论/视频（cursor.is_end=True 而 all_count 仍为数千），"
            "样本因此偏向高赞、高共识、易传播的表达；不代表评论区全量分布。",
            "仅覆盖 B站；未含米游社（页面为 JS 渲染）、NGA/贴吧/知乎（对匿名抓取返回 403）等渠道。",
            "发言者结构偏活跃、偏攻略向；'说的' 与 '做的' 未做交叉验证（无游戏内行为数据）。",
            "播放量/评论数/点赞数为采集时点快照，会随后续传播变化。",
            "热门评论会长期停留在榜首，故其发表时间可能早于口径窗口；早期评论已按 --since 排除并计数。",
        ],
    }
    log_path = os.path.splitext(args.out)[0] + "_log.json"
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=2)

    print("\n=== 完成 ===")
    print("反馈原始表 : %s（%d 行 / %d 名去重用户）" % (args.out, len(rows), users))
    print("采集日志   : %s" % log_path)
    print("请求 %d | 成功 %d | 失败 %d | 评论 原始 %d → 保留 %d（短评丢弃 %d / 窗口外丢弃 %d）"
          % (_stats["requests"], _stats["ok"], _stats["failed"],
             _stats["comments_raw"], len(rows), _stats["dropped_short"], _stats["dropped_out_of_window"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
