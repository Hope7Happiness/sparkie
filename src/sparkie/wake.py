"""Leading wake-name detection; request wording is unrestricted."""
import re

ADDRESS = re.compile(r"^\s*(?:(?:hey|hi|hello)(?:\s*[,，.!?。！？]\s*|\s+))?spark(?:ie|y)(?=$|[\s,，:：.!?。！？]|[\u4e00-\u9fff])", re.I)
CANCEL = re.compile(r"^(?:没事|不用了|取消|算了|never\s*mind|cancel|stop)\b|^(?:没事|不用了|取消|算了)", re.I)


# A narrowly observed ASR rendering of the user's "hi Sparky" greeting.
# Don't search for names in arbitrary sentences or treat self-introductions as requests.
GREETING_ASR = re.compile(r"^\s*(?:hi|hey|hello)[\s,，.!?。！？]+it(?:['’]s|\s+is)\s+spark(?:ie|y)[\s.!?。！？]*$", re.I)


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
    return rest
