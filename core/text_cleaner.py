import re

class MessageCleaner:
    """
    The Brain: Pure synchronous text transformation.
    Strips competitor links and @handles, cleans whitespace,
    and injects custom client VIP signature.
    """
    # Regex matching URLs (http, https, www, t.me, bit.ly, etc.)
    URL_PATTERN = re.compile(
        r'(?:https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)',
        re.IGNORECASE
    )
    # Regex matching @usernames (Twitter and Telegram format)
    USERNAME_PATTERN = re.compile(r'@\w{1,32}')

    @classmethod
    def clean(cls, text: str, mode: int = 1, signature: str = "") -> str:
        """
        Modes:
          0 = Keep original text as-is
          1 = Strip all competitor URLs & @handles, append signature
          2 = Replace URLs & @handles with signature
          3 = Nuke entire text and replace with signature
        """
        if not text:
            return signature.strip() if signature else ""

        if mode == 0:
            return f"{text.strip()}\n\n{signature.strip()}".strip() if signature else text.strip()

        if mode == 3:
            return signature.strip()

        # Mode 1 & 2
        replacement = signature.strip() if mode == 2 else ""
        cleaned = cls.URL_PATTERN.sub(replacement, text)
        cleaned = cls.USERNAME_PATTERN.sub(replacement, cleaned)

        # Normalize redundant whitespace and blank lines
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned).strip()

        # Append signature if mode is 1
        if mode == 1 and signature:
            cleaned = f"{cleaned}\n\n{signature.strip()}".strip()

        return cleaned
