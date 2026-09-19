"""Conservative address detection; real ASR accuracy still needs a meeting test."""
import re

ADDRESS = re.compile(r"^\s*(?:(?:hey|hi|hello)(?:\s*[,，.!?。！？]\s*|\s+))?spark(?:ie|y)(?=$|[\s,，:：.!?。！？]|[\u4e00-\u9fff])", re.I)
CANCEL = re.compile(r"^(?:没事|不用了|取消|算了|never\s*mind|cancel|stop)\b|^(?:没事|不用了|取消|算了)", re.I)
REQUEST = re.compile(r"^(?:请|帮|总结|回答|查|你|我们|刚才|现在|听|在吗|说|告诉|整理|分析|调研|能|可以|什么|为什么|怎么|哪|谁|是否|解释|what\b|why\b|how\b|who\b|when\b|where\b|which\b|explain\b|can\b|could\b|please\b|summari[sz]e\b|tell\b|are\b|do\b|did\b|find\b|research\b|hello\b)", re.I)


# A narrowly observed ASR rendering of the user's "hi Sparky" greeting.
# Don't search for names in arbitrary sentences or treat self-introductions as requests.
GREETING_ASR = re.compile(r"^\s*(?:hi|hey|hello)[\s,，.!?。！？]+it(?:['’]s|\s+is)\s+spark(?:ie|y)[\s.!?。！？]*$", re.I)
YES_NO_QUESTION = re.compile(r"^(?:is|isn't|was|were|will|would|should|does|has|have)\b", re.I)


def addressed_request(text: str) -> str | None:
    if GREETING_ASR.fullmatch(text):
        return ""
    match = ADDRESS.match(text)
    if not match:
        return None
    rest = text[match.end():].strip(" \t\n,，:：.!?。！？")
    # Repeated calls often arrive in one final ASR segment.
    while repeated := ADDRESS.match(rest):
        rest = rest[repeated.end():].strip(" \t\n,，:：.!?。！？")
    if CANCEL.search(rest):
        return None
    explicit_question = text.rstrip().endswith(("?", "？")) and text[match.end():].lstrip().startswith((",", ".", ":", "，", "。", "："))
    if not rest or REQUEST.search(rest) or (explicit_question and YES_NO_QUESTION.search(rest)):
        return rest
    return None
