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
    "volleyball": ["volleyball", "vball"],
    "lacrosse": ["lacrosse", "lax"],
    "rugby": ["rugby"],
    # Individual / racquet / other sports
    "swim": ["swim", "swimming", "aquatics", "learn to swim"],
    "tennis": ["tennis"],
    "racquet": ["racquet", "racket", "squash", "badminton"],
    "golf": ["golf"],
    "track": ["track", "track and field", "running", "cross country", "xc"],
    "cycling": ["cycling", "biking", "bmx", "mountain bike"],
    "climbing": ["climbing", "rock climbing", "bouldering"],
    "skating": ["skating", "ice skating", "roller skating", "skateboarding", "skateboard"],
    "skiing": ["skiing", "ski", "snowboard", "snowboarding"],
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
    "cheerleading": ["cheerleading", "cheer", "cheerleader"],
    "dance": ["dance", "ballet", "jazz dance", "hip hop", "tap"],
    "yoga": ["yoga"],
    "gym": ["gym", "gymnastics", "tumbling", "fitness", "parkour"],
    # Enrichment
    "art": ["art", "painting", "drawing", "ceramics", "pottery", "crafts"],
    "music": ["music", "piano", "guitar", "violin", "orchestra", "chorus", "singing"],
    "theater": ["theater", "theatre", "drama", "acting", "musical theater"],
    "stem": ["stem", "science", "robotics", "engineering", "math"],
    "coding": ["coding", "programming", "code", "computer science"],
    "chess": ["chess"],
    "academic": ["academic", "tutoring", "reading", "writing", "language", "spanish"],
    "cooking": ["cooking", "baking", "culinary"],
    # Umbrella
    "multisport": ["multisport", "multi sport", "sports sampler"],
    "outdoor": ["outdoor", "hiking", "camping"],
    "nature": ["nature", "naturalist", "wildlife"],
    "camp_general": ["camp", "summer camp", "day camp"],
}
