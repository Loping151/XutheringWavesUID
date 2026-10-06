import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from gsuid_core.aps import scheduler
from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ImageEntity, KnowledgePoint
from gsuid_core.ai_core.register import ai_alias, ai_entity, ai_image

from ..utils.resource.RESOURCE_PATH import (
    GUIDE_PATH,
    MAP_PATH,
    MAP_DETAIL_PATH,
    MAP_CHALLENGE_PATH,
)
from ..utils.resource.constant import ATTRIBUTE_ID_MAP, WEAPON_TYPE_ID_MAP
from ..utils.util import format_with_defaults

HELP_JSON_PATH = Path(__file__).parent.parent / "wutheringwaves_help" / "help.json"

# 这些 section 下的命令带副作用，KP 里追加"AI 不可代为执行"提示
_WRITE_HELP_SECTIONS = {
    "绑定账号",
    "库街区登录",
    "个人服务",
    "群管理员功能",
    "bot主人功能",
    "面板图帮助",
}
# 这些命令名是 section 内**例外**的副作用项（其它命令是只读的）
_WRITE_HELP_NAMES = {
    "导入抽卡链接", "导入工坊抽卡记录", "导出抽卡记录", "删除抽卡记录",
    "鸣潮面板更新",  # 信息查询里这个有 API 副作用
}

PLUGIN = "XutheringWavesUID"
_HTML_RE = re.compile(r"<[^>]+>")

ATTR_MAP = ATTRIBUTE_ID_MAP
WEAPON_TYPE_MAP = WEAPON_TYPE_ID_MAP
GUIDE_AUTHORS = {
    "XMu": "小沐XMu",
    "Moealkyne": "Moealkyne",
    "JinLingZi": "金铃子攻略组",
    "VanZi": "結星",
    "XiaoYang": "小羊",
    "WuHen": "吃我无痕",
    "XFM": "巡游天国",
    "KuroBBS": "社区攻略",
    "Lagvar": "拉格朗日变分主义",
}


def _strip(s: Any) -> str:
    if not s:
        return ""
    return _HTML_RE.sub("", str(s)).strip()


def _kp(eid: str, title: str, content: str, tags: List[str]) -> KnowledgePoint:
    return KnowledgePoint(
        id=eid, plugin=PLUGIN, title=title, content=content,
        tags=tags, source="plugin", _hash="",
    )


def _iter_jsons(d: Path) -> Iterable[Tuple[str, Any]]:
    if not d.exists():
        return
    for p in sorted(d.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                yield p.stem, json.load(f)
        except Exception as e:
            logger.warning(f"[鸣潮·AI-RAG] 跳过 {p.name}: {e}")


def _sorted_keys(d: Dict) -> List:
    return sorted(d.keys(), key=lambda x: int(x) if str(x).lstrip("-").isdigit() else 9999)


def _load_forte(cid: str) -> Optional[Dict]:
    """读取 forte/<cid>/forte.json，返回 dict 或 None。"""
    fp = MAP_DETAIL_PATH / "forte" / cid / "forte.json"
    if not fp.exists():
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[鸣潮·AI-RAG] 读取 forte {cid} 失败: {e}")
        return None


def _max_stat(stats: Optional[Dict]) -> Optional[Tuple[str, str, Any]]:
    """从 char/weapon.stats 中提取最高突破 + 最高等级的面板。返回 (breach_k, lv_k, payload) 或 None。"""
    if not isinstance(stats, dict) or not stats:
        return None
    bk = max(stats.keys(), key=lambda x: int(x) if str(x).isdigit() else -1)
    inner = stats.get(bk)
    if not isinstance(inner, dict) or not inner:
        return None
    lk = max(inner.keys(), key=lambda x: int(x) if str(x).isdigit() else -1)
    return bk, lk, inner[lk]


def _format_weapon_stat(payload: Any) -> str:
    """weapon.stats[breach][lv] 是 list of {name,value,isPercent,...}，拼成可读串。
    格式化与 utils/ascension/weapon.py 一致: isPercent → /100, isRatio → *100, else → int。"""
    if not isinstance(payload, list):
        return str(payload)
    parts = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        nm = item.get("name", "?")
        v = item.get("value")
        try:
            if item.get("isPercent"):
                v = f"{float(v) / 100:.1f}%"
            elif item.get("isRatio"):
                v = f"{float(v) * 100:.1f}%"
            else:
                v = f"{int(float(v))}"
        except (TypeError, ValueError):
            pass
        parts.append(f"{nm} {v}")
    return " | ".join(parts)


def _register_chars(aliases: Dict[str, List[str]]) -> List[Tuple]:
    summary = []
    for cid, d in _iter_jsons(MAP_DETAIL_PATH / "char"):
        name = d.get("name", cid)
        star = d.get("starLevel", "-")
        attr = ATTR_MAP.get(d.get("attributeId"), str(d.get("attributeId", "?")))
        wt = WEAPON_TYPE_MAP.get(d.get("weaponTypeId"), str(d.get("weaponTypeId", "?")))
        alias_list = aliases.get(name, [])
        tags = ["角色", name, cid, attr, wt, f"{star}星", *alias_list]

        profile = [
            f"# {name} | ID {cid}",
            f"- 星级：{star}星  属性：{attr}  武器：{wt}",
        ]
        if alias_list:
            profile.append(f"- 别名：{', '.join(alias_list)}")

        max_stat = _max_stat(d.get("stats"))
        if max_stat:
            bk, lk, payload = max_stat
            if isinstance(payload, dict):
                profile.append(
                    f"- 满级面板 (突破{bk}/Lv{lk}): "
                    f"生命 {int(payload.get('life', 0))} | 攻击 {int(payload.get('atk', 0))} | 防御 {int(payload.get('def', 0))}"
                )

        forte = _load_forte(cid)
        if forte:
            features = forte.get("Features") or []
            if features:
                profile.append("\n## 玩法定位")
                for feat in features:
                    profile.append(f"- {_strip(feat)}")
            instructions = forte.get("Instructions") or {}
            if instructions:
                profile.append("\n## 机制详解")
                for ins in instructions.values():
                    if not isinstance(ins, dict):
                        continue
                    ins_name = ins.get("Name", "?")
                    ins_descs = ins.get("Desc") or {}
                    profile.append(f"\n### {ins_name}")
                    for sub in ins_descs.values():
                        if isinstance(sub, dict) and sub.get("Desc"):
                            profile.append(f"- {_strip(sub['Desc'])}")

        chains = d.get("chains") or {}
        if chains:
            profile.append("\n## 共鸣链")
            for k in _sorted_keys(chains):
                c = chains[k]
                profile.append(f"- 第{k}链 {c.get('name', '?')}: {_strip(c.get('desc'))}")
        ai_entity(_kp(f"ww_char_{cid}_profile", f"{name} 角色档案",
                      "\n".join(profile), tags + ["共鸣链", "档案", "玩法定位", "机制"]))

        skill_lines = [f"# {name} 技能与天赋"]
        for k in _sorted_keys(d.get("skillTree") or {}):
            sk = (d["skillTree"][k] or {}).get("skill") or {}
            sk_name, sk_type, sk_desc = sk.get("name"), sk.get("type"), _strip(sk.get("desc"))
            if not sk_name and not sk_desc:
                continue
            skill_lines.append(f"\n## [{sk_type or '技能'}] {sk_name or '?'}\n{sk_desc}")
        ai_entity(_kp(f"ww_char_{cid}_skill", f"{name} 技能与天赋",
                      "\n".join(skill_lines), tags + ["技能", "天赋"]))

        summary.append((cid, name, star, attr, wt))
    return summary


def _register_weapons(aliases: Dict[str, List[str]]) -> List[Tuple]:
    summary = []
    for wid, d in _iter_jsons(MAP_DETAIL_PATH / "weapon"):
        name = d.get("name", wid)
        star = d.get("starLevel", "-")
        wtype = WEAPON_TYPE_MAP.get(d.get("type"), str(d.get("type", "?")))
        alias_list = aliases.get(name, [])
        tags = ["武器", name, wid, f"{star}星", wtype, *alias_list]

        parts = [
            f"# {name} | ID {wid}",
            f"- 星级：{star}星  类型：{wtype}",
        ]
        if alias_list:
            parts.append(f"- 别名：{', '.join(alias_list)}")
        if d.get("desc"):
            parts.append(f"- 描述：{_strip(d.get('desc'))}")

        max_stat = _max_stat(d.get("stats"))
        if max_stat:
            bk, lk, payload = max_stat
            stat_text = _format_weapon_stat(payload)
            if stat_text:
                parts.append(f"- 满级面板 (突破{bk}/Lv{lk}): {stat_text}")

        effect = _strip(d.get("effect"))
        if effect:
            parts.append(f"\n## 效果 - {d.get('effectName', '')}\n{effect}")

        param = d.get("param") or []
        if param and isinstance(param, list):
            parts.append("\n## 谐振数值表（谐振 1 → 5）")
            for i, row in enumerate(param):
                if isinstance(row, list) and row:
                    parts.append(f"- 参数{i}: {' / '.join(str(x) for x in row)}")

        ai_entity(_kp(f"ww_weapon_{wid}", f"{name} 武器", "\n".join(parts),
                      tags + ["谐振", "数值表"]))
        summary.append((wid, name, star, wtype))
    return summary


def _register_echoes(aliases: Dict[str, List[str]]):
    for eid, d in _iter_jsons(MAP_DETAIL_PATH / "echo"):
        name = d.get("name", eid)
        alias_list = aliases.get(name, [])
        cost = d.get("intensityCode")
        group = d.get("group") or {}
        group_names = [
            (g.get("name") if isinstance(g, dict) else None) or ""
            for g in group.values()
        ]
        group_names = [g for g in group_names if g]

        skill_obj = d.get("skill") or {}
        if isinstance(skill_obj, dict):
            desc_raw = skill_obj.get("desc") or ""
            params = skill_obj.get("params") or []
            # desc 是 nanoka 模板({0} 占位), 用满级 params 渲染; 预渲染成品无占位则原样返回
            if desc_raw and params and isinstance(params[0], list):
                desc_raw = format_with_defaults(desc_raw, params[-1])
            skill_desc = _strip(desc_raw)
            simple = _strip(skill_obj.get("simpleDesc"))
        else:
            skill_desc, simple = _strip(skill_obj), ""

        lines = [f"# {name} | ID {eid}"]
        meta = []
        if cost is not None:
            meta.append(f"cost {cost}")
        if group_names:
            meta.append(f"所属套装：{', '.join(group_names)}")
        if meta:
            lines.append("- " + " | ".join(meta))
        if simple:
            lines.append(f"\n## 简介\n{simple}")
        if skill_desc:
            lines.append(f"\n## 技能详情\n{skill_desc}")

        tags = ["声骸", name, eid, *alias_list, *group_names]
        if cost is not None:
            tags.extend([f"cost{cost}", f"{cost}费"])

        ai_entity(_kp(f"ww_echo_{eid}", f"{name} 声骸", "\n".join(lines), tags))


def _register_sonatas(aliases: Dict[str, List[str]]):
    for sid, d in _iter_jsons(MAP_DETAIL_PATH / "sonata"):
        name = d.get("name", sid)
        alias_list = aliases.get(name, [])
        tags = ["合鸣", "声骸套装", name, sid, *alias_list]
        sets = d.get("set") or {}
        lines = [f"# {name} 合鸣"]
        if alias_list:
            lines.append(f"- 别名：{', '.join(alias_list)}")
        for k in _sorted_keys(sets):
            lines.append(f"\n## {k}件套\n{_strip(sets[k])}")
        ai_entity(_kp(f"ww_sonata_{sid}", f"{name} 合鸣套装", "\n".join(lines), tags))


def _period_label(num: int, current: int) -> Tuple[str, List[str]]:
    """返回 (一段中文状态描述, 该期对应的相对期 tag 列表)。非当期附近返回空。"""
    delta = num - current
    if delta == 0:
        return f"🔴 本期 (当期，第{current}期)", ["当期", "本期", "现在", "正在进行"]
    if delta == -1:
        return f"🟡 上一期 (当前第{current}期)", ["上一期", "上期"]
    if delta == 1:
        return f"🟢 下一期 (当前第{current}期，下期即将到来)", ["下一期", "下期", "即将"]
    return "", []


def _format_buffs(buffs: Dict) -> str:
    return "\n".join(f"- {_strip((b or {}).get('Desc'))}" for b in (buffs or {}).values()) if buffs else ""


def _format_monsters(monsters: Dict) -> str:
    if not monsters:
        return ""
    return ", ".join(
        f"{m.get('Name', '?')}({ATTR_MAP.get(m.get('Element'), '-')} Lv{m.get('Level', '-')})"
        for m in monsters.values()
    )


def _register_tower(monster_index: Dict[str, List[str]]):
    from ..wutheringwaves_abyss.period import get_tower_period_number
    current = get_tower_period_number()
    for tid, d in _iter_jsons(MAP_CHALLENGE_PATH / "tower"):
        begin, end = d.get("Begin", "?"), d.get("End", "?")
        try:
            label, extra_tags = _period_label(int(tid), current)
        except ValueError:
            label, extra_tags = "", []
        lines = [
            f"# 鸣潮 · 逆境深塔 第{tid}期",
            "",
            "**逆境深塔**（官方英文名 Tower of Adversity）是稷廷遗留的实验设施，瑝珑改造后变为战力演算项目，"
            "可将记忆中的敌人具现化训练。分为「稳定区」「实验区」「深境区」三大区域，每个区域含若干「塔」，"
            "每个塔由多层挑战构成；通过前一区域全部难度后开启下一区域。",
            "",
            "机制要点：每完成一层会扣除共鸣者疲劳值，疲劳不足则该角色无法出战；存在「深境干扰」环境效果；"
            "稳定/实验区固定不变只奖励一次，**深境区周期重置**，按印记数兑换星声与「深境记录」代币。",
        ]
        if label:
            lines.append(f"- 状态：{label}")
        lines.append(f"- 开放时间：{begin} ~ {end}")
        for area_k in _sorted_keys(d.get("Area") or {}):
            area = d["Area"][area_k]
            lines.append(f"\n## 区域 {area_k}")
            floors = area.get("Floor") or {}
            for fk in _sorted_keys(floors):
                f_data = floors[fk]
                lines.append(f"\n### 第{fk}层 (体力 {f_data.get('Cost', '?')})")
                buffs = _format_buffs(f_data.get("Buffs"))
                if buffs:
                    lines.append(f"**Buff**：\n{buffs}")
                ms = f_data.get("Monsters") or {}
                if ms:
                    lines.append(f"**怪物**：{_format_monsters(ms)}")
                    for m in ms.values():
                        n = m.get("Name", "?")
                        monster_index.setdefault(n, []).append(f"深塔第{tid}期-区域{area_k}-第{fk}层")
        ai_entity(_kp(f"ww_tower_{tid}", f"鸣潮逆境深塔 第{tid}期", "\n".join(lines),
                      ["深塔", "逆境深塔", "Tower of Adversity",
                       "鸣潮", "高难度", "爬塔",
                       f"第{tid}期", tid, *extra_tags]))


def _register_slash():
    from ..wutheringwaves_abyss.period import get_slash_period_number
    current = get_slash_period_number()
    for sid, d in _iter_jsons(MAP_CHALLENGE_PATH / "slash"):
        items = d.get("BuffItems") or []
        if not items:
            continue
        try:
            label, extra_tags = _period_label(int(sid), current)
        except ValueError:
            label, extra_tags = "", []
        lines = [
            f"# 鸣潮 · 冥歌海墟 第{sid}期",
            "",
            "**冥歌海墟**（官方英文名 Whimpering Wastes）是 2.1 版本上线的常驻高难度副本，"
            "玩法定位与逆境深塔类似但独立。分多层挑战，从第 9 层开始上下半部分引入不同的属性抗性，"
            "需根据当期 Buff 与抗性灵活组队。",
            "",
            "本期可选 Buff（信物）列表如下，玩家按主 C 输出类型挑选叠加。",
        ]
        if label:
            lines.append(f"- 状态：{label}")
        for it in items:
            if not isinstance(it, dict):
                continue
            lines.append(f"- {it.get('Name', '?')}: {_strip(it.get('Desc'))}")
        ai_entity(_kp(f"ww_slash_{sid}", f"冥歌海墟 第{sid}期", "\n".join(lines),
                      ["海墟", "冥歌海墟", f"第{sid}期", sid, *extra_tags]))


def _register_matrix(monster_index: Dict[str, List[str]]):
    from ..wutheringwaves_abyss.period import get_matrix_period_number
    current = get_matrix_period_number()
    for mid, d in _iter_jsons(MAP_CHALLENGE_PATH / "matrix"):
        if not isinstance(d, dict):
            continue
        name = d.get("Name") or d.get("SeasonName") or f"矩阵-{mid}"
        season = d.get("SeasonName") or d.get("Season") or ""
        cycle = d.get("CycleName") or ""
        end_ver = d.get("EndVersion") or ""
        try:
            label, extra_tags = _period_label(int(mid), current)
        except ValueError:
            label, extra_tags = "", []

        lines = [
            f"# 鸣潮 · 全息矩阵 第{mid}期 - {name}",
            "",
            "**全息矩阵**（官方英文名 Endstate Matrix）是鸣潮的周期挑战玩法，"
            "每期数据按周期约 42 天轮换。本期具体关卡、Buff 和推荐角色见下文。",
            "",
            "**重要语义对齐**：玩家口中的「矩阵」**通常特指当期「奇点扩张」关卡**"
            "（每期第 2 个关卡、难度更高、敌人更多）。「稳态协议」是前置较易关卡。",
        ]
        if label:
            lines.append(f"- 状态：{label}")
        lines.append(
            f"- 赛季：{season} | 周期：{cycle} | 截止版本：{end_ver}"
        )

        levels = d.get("Levels") or []
        level_names: List[str] = []
        monster_names: List[str] = []
        if levels:
            lines.append("\n## 关卡列表")
            for lv in levels:
                if not isinstance(lv, dict):
                    continue
                lv_id = lv.get("Id")
                lv_name = lv.get("Name") or f"关卡-{lv_id}"
                level_names.append(str(lv_name))
                team_limit = lv.get("TeamLimit")
                line = f"\n### 关卡 {lv_id} - {lv_name}"
                if team_limit:
                    line += f"（队伍人数：{team_limit}）"
                lines.append(line)
                buffs = lv.get("NewTowerBuffs") or []
                if buffs:
                    lines.append("**Buff 效果：**")
                    for b in buffs:
                        if not isinstance(b, dict):
                            continue
                        lines.append(
                            f"- {b.get('Name', '?')}: {_strip(b.get('Desc'))}"
                        )
                waves = lv.get("Waves") or []
                if waves:
                    lines.append("**敌人 / Boss：**")
                    for w in waves:
                        if not isinstance(w, dict):
                            continue
                        mname = w.get("Name", "?")
                        mlv = w.get("MonsterLevel", "?")
                        mdesc = _strip(w.get("Desc"))
                        tags_list = w.get("Tags") or []
                        tag_str = ", ".join(
                            (t.get("Name", "") if isinstance(t, dict) else "")
                            for t in tags_list
                        )
                        head = f"- **{mname}** (Lv{mlv})"
                        if tag_str:
                            head += f" 抗性: {tag_str}"
                        lines.append(head)
                        if mdesc:
                            lines.append(f"  - 机制: {mdesc}")
                        if mname not in monster_names:
                            monster_names.append(mname)
                        monster_index.setdefault(mname, []).append(
                            f"矩阵第{mid}期-{lv_name}"
                        )

        roles = d.get("Roles") or []
        if roles:
            lines.append("\n## 推荐角色与加成")
            for r in roles:
                if not isinstance(r, dict):
                    continue
                info = r.get("RoleInfo") or {}
                rname = info.get("Name") or str(r.get("Id", "?"))
                quality = info.get("QualityId")
                rline = f"\n### {rname}"
                if quality:
                    rline += f"（{quality}★）"
                lines.append(rline)
                for ed in r.get("EnhanceSkillDesc") or []:
                    if isinstance(ed, dict) and ed.get("Value"):
                        lines.append(f"- {_strip(ed['Value'])}")

        tags = [
            "矩阵", "全息矩阵", "Endstate Matrix",
            "鸣潮", "战斗玩法", "高难度", "Buff 加成", "敌人", "怪物", "Boss",
            str(name), f"第{mid}期", mid, *extra_tags,
        ]
        if season:
            tags.append(str(season))
        tags.extend(level_names)
        tags.extend(monster_names)

        ai_entity(_kp(
            f"ww_matrix_{mid}",
            f"鸣潮全息矩阵 第{mid}期 {name}",
            "\n".join(lines),
            tags,
        ))


def _register_summary(chars: List[Tuple], weapons: List[Tuple], monsters: Dict[str, List[str]]):
    if chars:
        lines = ["# 鸣潮全角色一览", "", "| ID | 名字 | 星级 | 属性 | 武器 |", "|---|---|---|---|---|"]
        for cid, name, star, attr, wt in chars:
            lines.append(f"| {cid} | {name} | {star}★ | {attr} | {wt} |")
        ai_entity(_kp("ww_summary_chars", "鸣潮全角色一览", "\n".join(lines),
                      ["角色", "汇总", "统计", "全角色"]))
    if weapons:
        lines = ["# 鸣潮全武器一览", "", "| ID | 名字 | 星级 | 类型 |", "|---|---|---|---|"]
        for wid, name, star, wt in weapons:
            lines.append(f"| {wid} | {name} | {star}★ | {wt} |")
        ai_entity(_kp("ww_summary_weapons", "鸣潮全武器一览", "\n".join(lines),
                      ["武器", "汇总", "统计", "全武器"]))
    if monsters:
        lines = ["# 鸣潮怪物索引（出场记录）", ""]
        for n in sorted(monsters):
            lines.append(f"- **{n}**: " + "; ".join(monsters[n]))
        ai_entity(_kp("ww_summary_monsters", "鸣潮怪物索引", "\n".join(lines),
                      ["敌人", "怪物", "汇总", "索引"]))


def _register_aliases(d: Dict[str, List[str]]):
    for main, lst in d.items():
        rest = [a for a in (lst or []) if a and a != main]
        if rest:
            ai_alias(main, rest)


def _register_period_indexes() -> int:
    """把深塔/海墟/矩阵的「期数-日期」全量索引注册成 KP。

    数据直接来自每期 JSON 的 Begin/End 字段（tower/slash）和 EndVersion（matrix），
    不靠 cycle 数学推算——应对游戏更新周期变更后历史数据仍然准确。

    返回注册的 KP 数（3 条）。
    """
    from .tools.period import get_tower_index, get_slash_index, get_matrix_index

    tower = get_tower_index()
    if tower:
        lines = [
            "# 鸣潮 · 逆境深塔 期数-日期索引表",
            "",
            "下表来自每期 JSON 的 `Begin`/`End` 字段，是精确起止日期。",
            "查询「某月某日是第几期深塔」时按此表 Begin <= 日期 <= End 命中。",
            "",
            f"共 {len(tower)} 期：",
            "",
            "| 期 | 开始 | 结束 |",
            "|---|---|---|",
        ]
        for e in tower:
            lines.append(f"| {e['period']} | {e['begin'] or '-'} | {e['end'] or '-'} |")
        ai_entity(_kp(
            "ww_period_index_tower",
            "鸣潮深塔期数-日期索引表",
            "\n".join(lines),
            ["深塔", "逆境深塔", "Tower of Adversity",
             "鸣潮", "期数", "日期索引", "开始时间", "结束时间", "周期"],
        ))

    slash = get_slash_index()
    if slash:
        lines = [
            "# 鸣潮 · 冥歌海墟 期数-日期索引表",
            "",
            "下表来自每期 JSON 的 `Begin`/`End` 字段。早期（0 期）可能缺时间。",
            "查询「某月某日是第几期海墟」时按此表 Begin <= 日期 <= End 命中。",
            "",
            f"共 {len(slash)} 期：",
            "",
            "| 期 | 开始 | 结束 |",
            "|---|---|---|",
        ]
        for e in slash:
            lines.append(f"| {e['period']} | {e['begin'] or '-'} | {e['end'] or '-'} |")
        ai_entity(_kp(
            "ww_period_index_slash",
            "鸣潮海墟期数-日期索引表",
            "\n".join(lines),
            ["海墟", "冥歌海墟", "Whimpering Wastes",
             "鸣潮", "期数", "日期索引", "无尽", "周期"],
        ))

    matrix = get_matrix_index()
    if matrix:
        lines = [
            "# 鸣潮 · 全息矩阵 期数-版本索引表",
            "",
            "⚠️ matrix 期 JSON **不含精确起止日期字段**，只有 EndVersion（截止游戏版本号）。",
            "查询「具体哪天对应第几期矩阵」需结合游戏公告，本索引仅给版本号映射。",
            "",
            f"共 {len(matrix)} 期：",
            "",
            "| 期 | 名称 | 赛季 | 截止版本 |",
            "|---|---|---|---|",
        ]
        for e in matrix:
            lines.append(
                f"| {e['period']} | {e['name'] or '-'} | "
                f"{e['season_name'] or '-'} | {e['end_version'] or '-'} |"
            )
        ai_entity(_kp(
            "ww_period_index_matrix",
            "鸣潮矩阵期数-版本索引表",
            "\n".join(lines),
            ["矩阵", "全息矩阵", "Endstate Matrix",
             "鸣潮", "期数", "版本索引", "赛季", "周期"],
        ))

    return sum(1 for x in (tower, slash, matrix) if x)


def _register_help_commands() -> int:
    """把 help 全部命令转成 KP。

    数据源走 wutheringwaves_help.get_help_data()，这样能同时拿到 help.json 静态条目
    **和** 按 HelpExtraModules 配置动态拼接的 RoverSign/TodayEcho/ScoreEcho/RoverReminder
    extras。fallback 到直接读 help.json。

    副作用命令只进 KP（不挂 to_ai），AI 知道存在但只能告知用户怎么发命令、不能代调。
    只读命令也写一份 KP，方便用户问"怎么用 XX"时检索到准确用法。
    """
    help_data = None
    try:
        from ..wutheringwaves_help.get_help import get_help_data
        help_data = get_help_data()
    except Exception as e:
        logger.warning(f"[鸣潮·AI-RAG] get_help_data() 调用失败，回退到直接读 help.json: {e}")
    if not help_data:
        if not HELP_JSON_PATH.exists():
            logger.warning(f"[鸣潮·AI-RAG] help.json 不存在: {HELP_JSON_PATH}")
            return 0
        try:
            with open(HELP_JSON_PATH, "r", encoding="utf-8") as f:
                help_data = json.load(f)
        except Exception as e:
            logger.warning(f"[鸣潮·AI-RAG] help.json 解析失败: {e}")
            return 0

    count = 0
    for section, sd in help_data.items():
        if not isinstance(sd, dict):
            continue
        section_is_write = section in _WRITE_HELP_SECTIONS
        for item in sd.get("data", []) or []:
            if not isinstance(item, dict):
                continue
            cmd_name = item.get("name") or "?"
            desc = item.get("desc") or ""
            eg = item.get("eg") or ""
            is_write = section_is_write or cmd_name in _WRITE_HELP_NAMES

            content_lines = [
                f"**命令**: `{cmd_name}`",
                f"**所属分组**: 鸣潮 - {section}",
                f"**说明**: {desc}",
                f"**用法示例**: {eg}",
            ]
            if is_write:
                content_lines.append("")
                content_lines.append(
                    "⚠️ 此命令存在副作用（修改 / 删除 / 上传 / 订阅 / 管理类等），"
                    "AI **不可代为执行**——只能告诉用户自己发对应命令完成。"
                )

            # tags 含命令名 + 示例首词 + section + 用法关键词
            eg_words = [w for w in eg.replace("/", " ").split() if w][:3]
            tags = ["鸣潮命令", "用法", "帮助", section, cmd_name, *eg_words]
            if is_write:
                tags.append("副作用")

            ai_entity(_kp(
                f"ww_help_{section}_{cmd_name}",
                f"鸣潮命令: {cmd_name}",
                "\n".join(content_lines),
                tags,
            ))
            count += 1
    return count


def _load_alias(name: str) -> Dict[str, List[str]]:
    p = MAP_PATH / "alias" / name
    if not p.exists():
        logger.warning(f"[鸣潮·AI-RAG] 别名文件缺失: {p}")
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[鸣潮·AI-RAG] 别名解析失败 {p}: {e}")
        return {}


def _clear_self_entries():
    """从全局 _ENTITIES / _IMAGE_ENTITIES 移除本插件旧数据，保证 register_all 可重入。"""
    from gsuid_core.ai_core.register import _ENTITIES, _IMAGE_ENTITIES
    _ENTITIES[:] = [e for e in _ENTITIES if e.get("plugin") != PLUGIN]
    _IMAGE_ENTITIES[:] = [e for e in _IMAGE_ENTITIES if e.get("plugin") != PLUGIN]


def _register_guides(char_meta: Dict[str, Dict]) -> int:
    """攻略图：按角色名命名 (折枝.jpg 等)，按作者分目录。"""
    if not GUIDE_PATH.exists():
        return 0
    count = 0
    for author_dir in sorted(GUIDE_PATH.iterdir()):
        if not author_dir.is_dir():
            continue
        author_zh = GUIDE_AUTHORS.get(author_dir.name, author_dir.name)
        for img in sorted(author_dir.iterdir()):
            if img.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            char_name = img.stem
            meta = char_meta.get(char_name, {})
            tags = ["攻略", "配装", author_zh, author_dir.name, char_name, *meta.get("aliases", [])]
            for k in ("cid", "attr", "wt"):
                v = meta.get(k)
                if v:
                    tags.append(str(v))
            if meta.get("star"):
                tags.append(f"{meta['star']}星")
            if char_name.startswith("矩阵"):
                tags.append("全息矩阵")
                content = f"{char_name} 版本全息矩阵的「{author_zh}」攻略图，包含配队与打法思路。"
            else:
                content = (
                    f"{char_name} 的「{author_zh}」攻略图。"
                    "通常包含推荐声骸 / 武器 / 共鸣链优先级 / 技能加点 / 伤害分析 / 配队思路等内容。"
                )
            ai_image(ImageEntity(
                id=f"ww_guide_{author_dir.name}_{char_name}",
                plugin=PLUGIN,
                path=str(img),
                tags=tags,
                content=content,
                source="plugin",
            ))
            count += 1
    return count


def register_all():
    # 先清旧实体: 即便资源缺失也得把上一次留下的 KP/Image 清掉, 避免向量库残留过期条目。
    _clear_self_entries()
    if not MAP_DETAIL_PATH.exists():
        logger.warning(f"[鸣潮·AI-RAG] {MAP_DETAIL_PATH} 不存在，跳过 wiki 注册")
        return
    aliases = {
        "char": _load_alias("char_alias.json"),
        "weapon": _load_alias("weapon_alias.json"),
        "sonata": _load_alias("sonata_alias.json"),
        "echo": _load_alias("echo_alias.json"),
    }
    chars = _register_chars(aliases["char"])
    weapons = _register_weapons(aliases["weapon"])
    _register_echoes(aliases["echo"])
    _register_sonatas(aliases["sonata"])
    monsters: Dict[str, List[str]] = {}
    _register_tower(monsters)
    _register_slash()
    _register_matrix(monsters)
    _register_summary(chars, weapons, monsters)
    char_meta = {
        name: {
            "cid": cid, "star": star, "attr": attr, "wt": wt,
            "aliases": aliases["char"].get(name, []),
        }
        for cid, name, star, attr, wt in chars
    }
    guide_count = _register_guides(char_meta)
    help_count = _register_help_commands()
    period_count = _register_period_indexes()
    for a in aliases.values():
        _register_aliases(a)
    logger.info(
        f"[鸣潮·AI-RAG] 注册完成: 角色 {len(chars)} | 武器 {len(weapons)} "
        f"| 怪物索引 {len(monsters)} | 攻略图 {guide_count} 张 "
        f"| 帮助命令 {help_count} 条 | 期数索引 {period_count} 条"
    )


async def reload_ai_rag():
    """资源下载后调用：重新注册 + 推送向量库同步。AI 未启用时自动 no-op。
    register_all 中途失败时回滚到旧实体状态, 避免内存里残留半成品。
    sync_knowledge 单独 try/except, 失败不影响 in-memory 已注册的新实体。"""
    from gsuid_core.ai_core.register import _ENTITIES, _IMAGE_ENTITIES
    own_entities_backup = [e for e in _ENTITIES if e.get("plugin") == PLUGIN]
    own_images_backup = [e for e in _IMAGE_ENTITIES if e.get("plugin") == PLUGIN]
    try:
        register_all()
    except Exception as e:
        _clear_self_entries()
        _ENTITIES.extend(own_entities_backup)
        _IMAGE_ENTITIES.extend(own_images_backup)
        logger.warning(f"[鸣潮·AI-RAG] register_all 失败, 已回滚到旧实体状态: {e}")
        return
    try:
        from . import tools as _tools  # noqa: F401
        _tools.invalidate_caches()
        from gsuid_core.ai_core.rag.knowledge import sync_knowledge
        await sync_knowledge()
    except Exception as e:
        logger.warning(f"[鸣潮·AI-RAG] 缓存失效/向量同步失败 (in-memory 已生效): {e}")


@scheduler.scheduled_job(
    "cron",
    hour=4,
    minute=1,
    id="ww_rag_periodic_reload",
)
async def waves_rag_periodic_reload():
    """每日 04:01 重新注册——让深塔/海墟/矩阵 KP 的「当期/上期/下期」标签随期数滚动。"""
    logger.info("[鸣潮·AI-RAG] 定时重注册触发")
    await reload_ai_rag()


register_all()

# 触发 tools.py 里的 @ai_tools 装饰器（必须在 register_all 之后，确保 AI 已就绪）
from . import tools as _tools_module  # noqa: F401, E402

# 注册"当期过场配队顾问"skill
from .skill import register_endgame_advisor_skill  # noqa: E402

register_endgame_advisor_skill()
