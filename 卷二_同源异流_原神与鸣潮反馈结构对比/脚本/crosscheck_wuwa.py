# -*- coding: utf-8 -*-
"""
独立交叉核验（《鸣潮》）— 用机械关键词共现估算各主题的量级，
用于校验锚定编码结果的数量级，识别编造或离谱频次。

性质声明：这不是主题编码，只是量级探针；类目由编码步骤从数据浮现。
用法：把结果与 编码/observations_coded.csv 的主题用户数对照，任何主题若显著高于探针上界，必须回查。
"""
import csv
import collections
import os

C = r"C:\Users\53656\Desktop\dsh简历\简历投递\米哈游_产品运营实习生-原神\作品集\作品集C_跨游戏反馈对比"
CSV = os.path.join(C, r"原始数据\wuthering_waves_strict_20260801_20261006.csv")

PROBES = {
    "高难副本/逆境深塔": ["逆境深塔", "深塔", "全息", "难度", "通关", "满星", "下潜"],
    "声骸/词条养成": ["声骸", "副词条", "主词条", "双爆", "专人专骸", "刷声骸", "调谐"],
    "强度膨胀/数值": ["膨胀", "强度", "数值", "dps", "DPS", "满命", "共鸣链", "倍率", "退环境"],
    "抽卡/福利/资源": ["抽", "保底", "歪", "星声", "福利", "兑换", "池子", "十连", "月卡"],
    "养成时间成本/肝度": ["体力", "太肝", "肝", "日常", "材料", "养成", "结晶", "刷本"],
    "活动玩法": ["活动", "限时", "奖励", "版本", "前瞻"],
    "剧情/世界观": ["剧情", "主线", "台词", "设定", "CV", "配音", "故事"],
    "大世界探索/跑图": ["探索", "地图", "宝箱", "解谜", "声匣", "跑图", "锚点"],
    "移动端/设备": ["卡顿", "掉帧", "手机", "闪退", "优化", "帧"],
    "联机/社交": ["联机", "组队", "队友", "好友"],
    "社区氛围/节奏": ["社区", "节奏", "举报", "孝子", "结晶", "对立", "骂", "拉踩"],
    "官方沟通/补偿": ["官方", "策划", "补偿", "道歉", "回应", "公告"],
    "美术/建模/演出": ["建模", "立绘", "演出", "皮肤", "外观", "好看"],
    "新手/回坑体验": ["萌新", "新手", "入坑", "看不懂", "引导", "教学", "回归"],
    "平台/社区跨游戏比较": ["原神", "崩铁", "米哈游", "库洛", "对比"],
}

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
by_user = collections.defaultdict(list)
for r in rows:
    by_user[r["用户编号"]].append(r["内容"])

print("样本：%d 条 / %d 用户 / %d 视频\n"
      % (len(rows), len(set(r["用户编号"] for r in rows)), len(set(r["来源视频"] for r in rows))))

res = []
for theme, kws in PROBES.items():
    users = sum(1 for texts in by_user.values()
                if any(k in " ".join(texts) for k in kws))
    res.append((users, theme))
res.sort(reverse=True)

print("%-6s %-8s %s" % ("用户数", "占比", "机械探针主题（仅供量级对照）"))
for users, theme in res:
    print("%-8d %6.1f%%   %s" % (users, 100.0 * users / len(by_user), theme))

hit = sum(1 for texts in by_user.values()
          if any(any(k in " ".join(texts) for k in kws) for kws in PROBES.values()))
print("\n至少命中一个探针的用户：%d / %d（%.1f%%）" % (hit, len(by_user), 100.0 * hit / len(by_user)))
print("未命中任何探针（≈玩梗/纯情绪/闲聊）：%d" % (len(by_user) - hit))
