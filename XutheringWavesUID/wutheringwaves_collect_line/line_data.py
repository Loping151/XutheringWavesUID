import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..utils.resource.constant import NAME_ALIAS, SPECIAL_CHAR_NAME, ID_FULL_CHAR_NAME
from ..utils.char_info_utils import get_all_role_detail_info_list


ROLE_FILE_CANDIDATES = (
    Path("D:/122/bot/xiaoyu/网页相关/角色.txt"),
    Path("D:/122/bot/xiaoyu/网页相关/roles.txt"),
    Path(__file__).parent / "roles.txt",
    Path("/root/bot/网页相关/角色.txt"),
)


@dataclass
class BingoCell:
    index: int
    role_name: str
    owned: bool
    role_id: str | None


@dataclass
class BingoAnswer:
    title: str
    size: int
    cells: list[BingoCell]
    owned_names: set[str]
    line_count: int
    line_paths: list[list[int]]


def normalize_role_name(name: str) -> str:
    return (
        name.strip()
        .replace(" ", "")
        .replace("\u3000", "")
        .replace("·", "")
        .replace("-", "")
        .replace("（", "(")
        .replace("）", ")")
        .lower()
    )


def _split_role_line(line: str) -> list[str]:
    line = line.strip().lstrip("\ufeff")
    if not line or line.startswith("#"):
        return []
    if re.fullmatch(r"[-—_＝=]+", line):
        return []
    if line in {"从左往右数", "从左往右", "从左到右", "按顺序"}:
        return []
    if re.match(r"^第[一二三四五六七八九十\d]+行\s*[:：]?$", line):
        return []
    if re.match(r"^(title|标题)\s*[:：=]", line, flags=re.I):
        return []
    if re.match(r"^(size|尺寸)\s*[:：=]", line, flags=re.I):
        return []

    # 支持这种写法：
    # 第一行：1.达妮娅2.漂泊者3.陆·赫斯4.赞妮5.露帕6.珂莱塔
    # 先去掉"第 N 行"前缀，再按阿拉伯数字编号切分。
    line = re.sub(r"^第[一二三四五六七八九十\d]+行\s*[:：]?\s*", "", line)
    numbered = re.findall(r"(?:^|(?<=\D))\d+[.、]\s*(.*?)(?=(?:\d+[.、])|$)", line)
    if numbered:
        return [i.strip() for i in numbered if i.strip()]

    return [i.strip() for i in re.split(r"[,，|/\t]+", line) if i.strip()]


def _read_role_file() -> tuple[str, int, list[str]] | str:
    role_file = next((p for p in ROLE_FILE_CANDIDATES if p.exists()), None)
    if role_file is None:
        return "未找到角色列表文件，请把 6x6 角色顺序写入：D:\\122\\bot\\xiaoyu\\网页相关\\角色.txt（一行一个角色）"

    raw = role_file.read_text(encoding="utf-8-sig")
    title = "鸣潮船新版本五星收集图"
    size = 6
    roles: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        title_match = re.match(r"^(title|标题)\s*[:：=]\s*(.+)$", stripped, flags=re.I)
        if title_match:
            title = title_match.group(2).strip() or title
            continue
        size_match = re.match(r"^(size|尺寸)\s*[:：=]\s*(\d+)$", stripped, flags=re.I)
        if size_match:
            size = int(size_match.group(2))
            continue
        roles.extend(_split_role_line(stripped))

    required = size * size
    if len(roles) < required:
        return (
            f"角色列表数量不够：当前 {len(roles)} 个，需要 {required} 个。\n"
            f"请补全 {role_file}，建议一行一个角色，顺序就是 Bingo 格子顺序。"
        )
    return title, size, roles[:required]


def _role_match_keys(role_name: str) -> set[str]:
    keys = {normalize_role_name(role_name)}
    if role_name in NAME_ALIAS:
        keys.add(normalize_role_name(NAME_ALIAS[role_name]))
    for full_name, alias in NAME_ALIAS.items():
        if role_name == alias:
            keys.add(normalize_role_name(full_name))
    if role_name == "漂泊者":
        keys.update(
            normalize_role_name(i)
            for i in (
                "漂泊者·衍射",
                "漂泊者·湮灭",
                "漂泊者·气动",
                "漂泊者·导电",
                "光主",
                "暗主",
                "风主",
                "雷主",
            )
        )
    return keys


def _owned_match_keys(name: str, role_id: str | int | None) -> set[str]:
    keys = _role_match_keys(name)
    if role_id is not None:
        rid = str(role_id)
        if rid in SPECIAL_CHAR_NAME:
            keys.add(normalize_role_name(SPECIAL_CHAR_NAME[rid]))
        if rid in ID_FULL_CHAR_NAME:
            keys.add(normalize_role_name(ID_FULL_CHAR_NAME[rid]))
    return keys


def _count_lines(answer: list[bool], size: int) -> tuple[int, list[list[int]]]:
    paths: list[list[int]] = []
    for row in range(size):
        path = [row * size + col for col in range(size)]
        if all(answer[i] for i in path):
            paths.append(path)
    for col in range(size):
        path = [row * size + col for row in range(size)]
        if all(answer[i] for i in path):
            paths.append(path)
    path = [i * size + i for i in range(size)]
    if all(answer[i] for i in path):
        paths.append(path)
    path = [(i + 1) * (size - 1) for i in range(size)]
    if all(answer[i] for i in path):
        paths.append(path)
    return len(paths), paths


async def _load_owned_roles(uid: str) -> tuple[set[str], dict[str, str]] | str:
    role_iter = await get_all_role_detail_info_list(uid)
    if not role_iter:
        return "未找到该 UID 的角色面板缓存，请先使用「ww刷新练度统计」或「ww刷新角色列表」生成角色数据后再试。"

    owned_keys: set[str] = set()
    key_to_id: dict[str, str] = {}
    for role_detail in role_iter:
        role = role_detail.role
        role_name = role.roleName
        role_id = str(role.roleId)
        for key in _owned_match_keys(role_name, role_id):
            owned_keys.add(key)
            key_to_id.setdefault(key, role_id)
    return owned_keys, key_to_id


def _first_hit(keys: Iterable[str], owned: set[str]) -> str | None:
    for key in keys:
        if key in owned:
            return key
    return None


async def build_bingo_answer(uid: str) -> BingoAnswer | str:
    role_file_data = _read_role_file()
    if isinstance(role_file_data, str):
        return role_file_data

    owned_data = await _load_owned_roles(uid)
    if isinstance(owned_data, str):
        return owned_data

    title, size, template_roles = role_file_data
    owned_keys, key_to_id = owned_data
    cells: list[BingoCell] = []
    answer: list[bool] = []
    for index, role_name in enumerate(template_roles):
        keys = _role_match_keys(role_name)
        hit = _first_hit(keys, owned_keys)
        owned = hit is not None
        answer.append(owned)
        cells.append(
            BingoCell(
                index=index,
                role_name=role_name,
                owned=owned,
                role_id=key_to_id[hit] if hit is not None and hit in key_to_id else None,
            )
        )

    line_count, line_paths = _count_lines(answer, size)
    return BingoAnswer(
        title=title,
        size=size,
        cells=cells,
        owned_names=owned_keys,
        line_count=line_count,
        line_paths=line_paths,
    )
