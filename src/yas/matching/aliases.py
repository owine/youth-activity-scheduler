"""Interest-name alias map, keyed by ProgramType value."""

from __future__ import annotations

INTEREST_ALIASES: dict[str, list[str]] = {
    # Team sports
    "soccer": ["soccer", "futbol", "kickers"],
    "baseball": [
        "baseball",
        "t ball",
        "tball",
        "t-ball",
        "coach pitch",
        "little league",
        "sluggers",
    ],
    "softball": ["softball", "fastpitch"],
    "basketball": ["basketball", "hoops"],
    "hockey": ["hockey", "ice hockey", "learn to skate"],
    "football": ["football", "flag football"],
    # Individual / other sports
    "swim": ["swim", "swimming", "aquatics", "learn to swim"],
    "martial_arts": [
        "martial arts",
        "karate",
        "taekwondo",
        "tae kwon do",
        "judo",
        "jiu jitsu",
        "bjj",
    ],
    "gymnastics": ["gymnastics", "tumbling"],
    "dance": ["dance", "ballet", "jazz dance", "hip hop", "tap"],
    "gym": ["gym", "gymnastics", "tumbling", "fitness", "parkour"],
    # Enrichment
    "art": ["art", "painting", "drawing", "ceramics", "pottery", "crafts"],
    "music": ["music", "piano", "guitar", "violin", "orchestra", "chorus", "singing"],
    "stem": ["stem", "science", "coding", "robotics", "engineering", "math"],
    "academic": ["academic", "tutoring", "reading", "writing", "language", "spanish"],
    # Umbrella
    "multisport": ["multisport", "multi sport", "sports sampler"],
    "outdoor": ["outdoor", "nature", "hiking", "camping"],
    "camp_general": ["camp", "summer camp", "day camp"],
}
