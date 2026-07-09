"""Tier 0: 원문 텍스트를 (발신자, 날짜, 시간, 원문라인들) 메시지 단위로 분리한다.

메신저 내보내기 특성상 한 메시지가 여러 줄(빈 줄 포함)일 수 있는데, 첫 줄에만
"이름 (HH:MM:SS) :" 접두사가 붙는다. 접두사 없는 줄은 전부 직전 메시지에
이어붙인다 — 새 메시지 시작이나 날짜 헤더가 나오기 전까지는 경계로 취급하지 않는다.
"""
from dataclasses import dataclass, field

from parser.taxonomy import DATE_HEADER_RE, MESSAGE_START_RE


@dataclass
class Message:
    source_file: str
    message_id: str
    sender: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM:SS
    lines: list = field(default_factory=list)


def parse_messages(text: str, source_file: str) -> list[Message]:
    messages: list[Message] = []
    current_date = None
    current: Message | None = None
    counter = 0

    def flush():
        if current is not None:
            messages.append(current)

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")

        date_match = DATE_HEADER_RE.match(line.strip())
        if date_match:
            flush()
            current = None
            year, month, day = date_match.groups()
            current_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            continue

        msg_match = MESSAGE_START_RE.match(line)
        if msg_match:
            flush()
            sender, hh, mm, ss, rest = msg_match.groups()
            counter += 1
            current = Message(
                source_file=source_file,
                message_id=f"{source_file}#{counter}",
                sender=sender.strip(),
                date=current_date,
                time=f"{hh}:{mm}:{ss}",
                lines=[rest],
            )
            continue

        # 접두사 없는 줄(빈 줄 포함) -> 현재 열린 메시지에 이어붙임
        if current is not None:
            current.lines.append(line)
        # current가 없으면 (헤더/메시지 시작 전 잡음) 그냥 버림

    flush()
    return messages
