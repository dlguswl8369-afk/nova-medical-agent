"""Whole terms plus Korean character bigrams; originals are never rewritten."""
import re
import unicodedata

# Keep codes, abbreviations, decimals and compound units intact AND index components.
TERM = re.compile(r"[가-힣]+|[a-zA-Zμµ]+[a-zA-Z0-9μµ]*(?:[./-][a-zA-Z0-9μµ]+)*|\d+(?:[.,]\d+)*(?:[%℃°])?|[%℃°†*]|[一-龥]+")
KOREAN = re.compile(r"[가-힣]+")


def tokenize(text, mode="ko_bigram"):
    if mode not in ("word", "ko_bigram"):
        raise ValueError(f"Unknown tokenizer: {mode}")
    normalized = unicodedata.normalize("NFC", text).casefold()
    tokens = []
    for match in TERM.finditer(normalized):
        word = match.group()
        tokens.append("w:" + word)
        if mode == "ko_bigram" and KOREAN.fullmatch(word) and len(word) > 2:
            tokens.extend("g:" + word[i:i + 2] for i in range(len(word) - 1))
        # Two-character whole Korean terms also match internal bigrams.
        elif mode == "ko_bigram" and KOREAN.fullmatch(word) and len(word) == 2:
            tokens.append("g:" + word)
        if not KOREAN.fullmatch(word) and re.search(r"[./-]", word):
            tokens.extend("w:" + x for x in re.split(r"[./-]", word) if x)
    return tokens
