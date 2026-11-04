nsfw_keywords = {
    "general": [
        "porn", "sex", "nude", "naked", "boobs", "tits", "pussy", "dick", "cock", "ass",
        "fuck", "blowjob", "cum", "orgasm", "shemale", "erotic", "masturbate", "anal",
        "hardcore", "bdsm", "fetish", "lingerie", "xxx", "milf", "gay", "lesbian",
        "threesome", "squirting", "butt plug", "dildo", "vibrator", "escort", "handjob",
        "striptease", "kinky", "pornstar", "sex tape", "spank", "swinger", "taboo", "cumshot",
        "deepthroat", "domination", "submission", "handcuffs", "orgy", "roleplay", "sex toy",
        "voyeur", "cosplay", "adult", "culture", "pornhwa",
        "netorare", "netori", "netorase", "eromanga", "incest", "stepmom", "stepdad",
        "stepsister", "stepbrother", "stepson", "stepdaughter", "ntr", "gangbang",
        "facial", "golden shower", "pegging", "rimming", "rough sex", "dirty talk",
        "sex chat", "nude pic", "lewd", "titty", "twerk", "breasts", "penis", "vagina",
        "clitoris", "genitals", "sexual", "kamasutra", "incest", "pedo", "rape", "bondage",
        "cum inside", "creampie", "sex slave", "sex doll", "sex machine", "latex", "oral sex",
        "butt", "slut", "whore", "tramp", "skank", "cumdumpster", "cultured", "ecchi", "doujin",
        "hentai", "smut", "lewd", "waifu", "futanari", "tentacle"
    ],
    "hentai": [
        "hentai", "doujinshi", "ecchi", "yaoi", "shota", "loli", "tentacle", "futanari",
        "bishoujo", "bishounen", "mecha hentai", "hentai manga", "hentai anime", "smut",
        "eroge", "visual novel", "h-manga", "h-anime", "adult manga", "18+ anime", "18+ manga",
        "lewd anime", "lewd manga", "animated porn", "animated sex", "hentai game", "hentai art",
        "hentai drawing", "hentai doujin", "yaoi hentai", "hentai comic",
        "hentai picture", "hentai scene", "hentai story", "hentai video", "hentai movie",
        "hentai episode", "hentai series"
    ],
    "abbreviations": [
        "pr0n", "s3x", "n00d", "fck", "bj", "hj", "l33t", "p0rn", "h3ntai", "h-ntai", "pnwh",
        "p0rnhwa", "l33tsp34k", "l3wd", "cultur3d", "s3xual"
    ],
    "offensive_slang": [
        "slut", "whore", "tramp", "skank", "cumdumpster", "gangbang", "facial", "golden shower",
        "pegging", "rimming", "rough sex", "dirty talk", "sex chat", "nude pic", "lewd", "titty",
        "twerk", "breasts", "penis", "vagina", "clitoris", "genitals", "sexual", "kamasutra",
        "incest", "pedo", "rape", "sex slave", "bondage", "creampie", "cum inside", "sex doll",
        "sex machine", "latex", "oral sex", "cumshot", "deepthroat", "domination", "submission",
        "handcuffs", "orgy", "roleplay", "sex toy", "voyeur", "cosplay", "adult", "culture",
        "anal", "erotic", "masturbate", "hardcore", "bdsm", "fetish", "lingerie", "milf", "taboo"
    ]
}

exception_keywords = ["nxivm", "classroom", "assassination", "geass"]

import re


def _build_pattern(words):
    # Whole-word / whole-phrase match only. The old plain substring check flagged
    # innocent names ("Class", "Object", "Control", "Introduction", "Grape",
    # "Document", "Torpedo" ...).
    parts = sorted({re.escape(w.lower()).replace(r"\ ", r"[\s._-]+") for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])")


_ALL_KEYWORDS = [kw for group in nsfw_keywords.values() for kw in group]
_NSFW_RE = _build_pattern(_ALL_KEYWORDS)


def is_nsfw_name(name: str) -> bool:
    lower_name = (name or "").lower()
    if any(k.lower() in lower_name for k in exception_keywords):
        return False
    return bool(_NSFW_RE.search(lower_name))


async def check_anti_nsfw(new_name, message):
    if is_nsfw_name(new_name):
        await message.reply_text("You can't rename files with NSFW content.")
        return True
    return False
