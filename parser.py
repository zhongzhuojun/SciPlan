from __future__ import annotations

import re

from rules import clamp_priority, parse_due


ACTION_START = r"(?:再|并且|并|然后|还要|另外|同时|以及|最后|需要|完成|检查|整理|提交|联系|阅读|分析|实验|写|跑|做|找|回复|跟进|重做|重跑|补)"


def _board(text: str):
    if re.search(r"论文|投稿|投出去|返修|审稿|评审|fig\.?|图\s*\d|写稿|期刊|杂志|稿件", text, re.I): return "paper", "论文"
    if re.search(r"基金|标书|预算|申报|申请书|答辩材料", text): return "grant", "标书"
    if re.search(r"实验|测序|分析|构建|样本|菌株|培养|数据|检测|突变|质粒|文库", text): return "research", "课题"
    return "misc", "杂事"


def _pieces(text: str) -> list[str]:
    normalized = re.sub(r"[\r\t]", " ", text).strip()
    normalized = re.sub(r"(?:^|\n)\s*(?:[-*•]|\d+[.)、])\s*", "\n", normalized)
    chunks = [p.strip(" ，,：:。；;！!？?\t") for p in re.split(r"[。；;！!？?\n]+", normalized) if p.strip()]
    out: list[str] = []
    for chunk in chunks:
        # Long meeting notes often put several actions in one comma-separated line.
        bits = re.split(rf"[，,]\s*(?={ACTION_START})", chunk)
        for bit in bits:
            bit = bit.strip(" ，,：:")
            if bit: out.append(bit)
    return out or [normalized]


def _title(text: str):
    clean = re.sub(r"^(我得|我需要|需要|记得|请|帮我|要|最好|然后|还要|麻烦|计划)\s*", "", text).strip(" ，,：:")
    clean = re.sub(r"(?:一下|吧|哦|呢)$", "", clean).strip()
    return clean[:28] or "未命名任务"


def parse(text: str, projects: list | None = None):
    projects = projects or []
    out = []
    for raw in _pieces(text):
        board_id, board_name = _board(raw)
        due = parse_due(raw)
        hours_m = re.search(r"(\d+(?:\.5)?)\s*(?:小时|个小时|h)", raw, re.I)
        if hours_m: hours = float(hours_m.group(1))
        elif re.search(r"半天", raw): hours = 4
        elif re.search(r"一天|全天", raw): hours = 8
        elif re.search(r"写|分析|实验|跑|画|构建|整理数据|测序", raw): hours = 4
        else: hours = 1
        hours = min((.5, 1, 2, 4, 8), key=lambda n: abs(n - hours))
        project_id = None
        for project in projects:
            pname = project.get("name") if isinstance(project, dict) else project
            if pname and pname.lower() in raw.lower():
                project_id = project.get("id") if isinstance(project, dict) else pname
                break
        urgency = 2 if re.search(r"催|赶紧|尽快|拖了|答应|必须|得在|前要|deadline|ddl", raw, re.I) else 3
        priority = clamp_priority(urgency, due, raw)
        reason = ("识别到截止时间" if due else "本地规则识别") + ("，含催办或承诺线索" if urgency == 2 else "")
        time_state = "dated" if due else ("window" if re.search(r"本周|这周|本月|月底|下周|等这批", raw) else "unknown")
        prereq_match = re.search(r"等(?:到|待)?(.{2,24}?)(?:回来|到位|完成|之后|后再|后才能|空档)?(?:再|后|才能|才)?", raw)
        prerequisite = prereq_match.group(1).strip(" ，,。；") if prereq_match and time_state == "unknown" else None
        out.append({"title": _title(raw), "board_id": board_id, "board": board_name, "project_id": project_id, "due": due, "time_state": time_state, "time_window": raw if time_state == "window" else None, "prerequisite": prerequisite, "purpose": None, "success_criteria": None, "dependencies": prerequisite, "est_hours": hours, "need_focus": bool(re.search(r"写|分析|实验|跑|画|构建|整理数据|测序", raw)), "priority": priority, "reason": reason, "raw": raw, "confidence": .78 if due or project_id else .62})
    return out
