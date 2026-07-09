"""tokenizer(Tier 0) + classifier(Tier 1) + extractor(Tier 2)를 orchestrate해서
data/ 폴더의 모든 .txt 채팅 로그를 하나의 pandas DataFrame으로 만든다.
"""
from pathlib import Path

import pandas as pd

from parser.classifier import classify
from parser.extractor import extract
from parser.tokenizer import parse_messages

COLUMNS = [
    "source_file",
    "sender",
    "date",
    "time",
    "datetime",
    "side_action",
    "is_live",
    "instrument_type",
    "tenor_raw",
    "tenor_legs",
    "tenor_unit",
    "rate_raw",
    "rate_1",
    "rate_2",
    "amount_eok",
    "clearing_tags",
    "raw_text",
    "message_id",
]


def build_rows(text: str, source_file: str) -> list[dict]:
    rows = []
    for msg in parse_messages(text, source_file):
        sub_lines = [line for line in msg.lines if line.strip() != ""]
        for sub_line in sub_lines:
            side_action, is_live = classify(sub_line)
            fields = extract(sub_line)
            dt = None
            if msg.date and msg.time:
                dt = pd.to_datetime(f"{msg.date} {msg.time}", errors="coerce")
            rows.append(
                {
                    "source_file": msg.source_file,
                    "sender": msg.sender,
                    "date": msg.date,
                    "time": msg.time,
                    "datetime": dt,
                    "side_action": side_action,
                    "is_live": is_live,
                    "raw_text": sub_line,
                    "message_id": msg.message_id,
                    **fields,
                }
            )
    return rows


def build_dataset(data_dir: str = "data") -> pd.DataFrame:
    rows: list[dict] = []
    for path in sorted(Path(data_dir).glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        rows.extend(build_rows(text, path.name))

    if not rows:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(rows, columns=COLUMNS)
    return df
