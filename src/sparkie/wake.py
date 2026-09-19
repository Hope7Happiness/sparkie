"""Conservative address detection; real ASR accuracy still needs a meeting test."""
import re

ADDRESS = re.compile(r"^\s*(?:hey[,，]?\s+)?spark(?:ie|y)(?=$|[\s,，:：.!?。！？]|[\u4e00-\u9fff])", re.I)
CANCEL = re.compile(r"^(?:没事|不用了|取消|算了|never\s*mind|cancel|stop)\b|^(?:没事|不用了|取消|算了)", re.I)
REQUEST = re.compile(r"^(?:请|帮|总结|回答|查|你|我们|刚才|现在|听|在吗|说|告诉|整理|分析|调研|能|可以|what\b|why\b|how\b|can\b|could\b|please\b|summari[sz]e\b|tell\b|are\b|do\b|find\b|research\b|hello\b)", re.I)


def addressed_request(text: str) -> str | None:
    match = ADDRESS.match(text)
    if not match:
        return None
    rest = text[match.end():].strip(" \t\n,，:：.!?。！？")
    if CANCEL.search(rest):
        return None
    if not rest or REQUEST.search(rest):
        return rest
    return None
