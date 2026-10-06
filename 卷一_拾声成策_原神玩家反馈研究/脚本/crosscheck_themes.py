# -*- coding: utf-8 -*-
"""
独立交叉核验：用机械关键词共现，估算各主题的「去重用户数」量级。
用途：当编码结果返回后，用它对照子代理报出的主题频次，识别数量级异常（防编造）。
注意：这不是主题编码，只是量级探针；类目必须由编码步骤从数据浮现。
"""
import csv
import collections
import os

CSV = r"C:\Users\53656\Desktop\dsh简历\简历投递\米哈游_产品运营实习生-原神\作品集\作品集A_原神玩家反馈分析\原始数据\bilibili_windowed_20261006.csv"

PROBES = {
    "高难玩法/幽境危战": ["幽境", "危战", "N5", "N6", "难度5", "难度6", "老头", "冰棺", "冰锅", "丘林"],
    "深渊/剧诗": ["深境", "深渊", "螺旋", "幻想真境", "剧诗", "12层", "满星"],
    "圣遗物/词条": ["圣遗物", "词条", "双爆", "爆伤", "暴击率", "沙漏"],
    "体力/树脂/肝度": ["体力", "树脂", "太肝", "肝", "日常", "周本", "清体力"],
    "配队/辅助抽取": ["配队", "辅助", "专辅", "通辅", "体系", "驾驶员", "金数", "0+0"],
    "抽卡/命座/氪金": ["抽", "命座", "满命", "歪", "up池", "氪", "月卡", "专武"],
    "角色强度讨论": ["强度", "数值", "膨胀", "dps", "DPS", "伤害", "输出", "深渊水温"],
    "萌新/入坑体验": ["萌新", "新手", "入坑", "看不懂", "引导", "教学", "不会玩"],
    "剧情/世界观": ["剧情", "主线", "台词", "设定", "世界观", "CV", "配音", "故事"],
    "地图探索": ["探索", "地图", "锚点", "宝箱", "解谜", "锚"],
    "活动/限时玩法": ["活动", "限时", "版本", "前瞻", "奖励", "原石"],
    "角色外观/XP": ["外观", "皮肤", "好看", "xp", "XP", "老婆", "老婆", "立绘"],
    "游戏卡顿/设备": ["卡顿", "掉帧", "手机", "闪退", "优化", "帧"],
    "联机/社交": ["联机", "队友", "组队", "好友", "奶妈", "奶不了"],
    "官方沟通/期望": ["官方", "策划", "回应", "道歉", "补偿", "期望", "宣传"],
}

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
print("样本：%d 条 / %d 用户 / %d 视频\n" % (len(rows), len(set(r["用户编号"] for r in rows)),
                                          len(set(r["来源视频"] for r in rows))))

# 按用户聚合（同一用户多条只算一次）
by_user = collections.defaultdict(list)
for r in rows:
    by_user[r["用户编号"]].append(r["内容"])

results = []
for theme, kws in PROBES.items():
    users, hits = 0, 0
    for uid, texts in by_user.items():
        joined = " ".join(texts)
        c = sum(joined.count(k) for k in kws)
        if c:
            users += 1
            hits += c
    results.append((users, hits, theme))

results.sort(reverse=True)
print("%-6s %-6s %-6s %s" % ("用户数", "命中数", "用户占比", "机械探针主题（仅供量级对照）"))
for users, hits, theme in results:
    print("%-8d %-8d %6.1f%%   %s" % (users, hits, 100.0 * users / len(by_user), theme))

coded_any = sum(1 for uid, texts in by_user.items()
                if any(sum(" ".join(texts).count(k) for k in kws) for kws in PROBES.values()))
print("\n至少命中一个探针的用户：%d / %d（%.1f%%）"
      % (coded_any, len(by_user), 100.0 * coded_any / len(by_user)))
print("未命中任何探针的用户（约等于玩梗/纯情绪/闲聊）：%d" % (len(by_user) - coded_any))
