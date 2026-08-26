"""Static troop type reference data — three tiers per bloodline. Seed via migration/script.
bloodline_key resolves to a Bloodline.id at seed time. Matches Section 4 of the design doc.

stats/resource_costs are starting placeholders — tune during playtesting, not final balance.
"""

TROOP_TYPES = [
    # --- Kindled ---
    {"bloodline_key": "kindled", "key": "emberguard", "name": "Emberguard", "tier": "basic",
     "ability_key": None, "stats": {"attack": 6, "defense": 2}, "resource_costs": {"sustenance": 4, "emberlight": 2}},
    {"bloodline_key": "kindled", "key": "cinder_archers", "name": "Cinder Archers", "tier": "support",
     "ability_key": "scorch", "stats": {"attack": 4, "defense": 1, "range": True},
     "resource_costs": {"sustenance": 5, "emberlight": 4}},
    {"bloodline_key": "kindled", "key": "wildfire_cavalry", "name": "Wildfire Cavalry", "tier": "signature",
     "ability_key": "blaze_trail", "stats": {"attack": 10, "defense": 3, "speed": "fast"},
     "resource_costs": {"emberdust": 6, "scrap": 5}},

    # --- Deepwell ---
    {"bloodline_key": "deepwell", "key": "tideguard", "name": "Tideguard", "tier": "basic",
     "ability_key": None, "stats": {"attack": 3, "defense": 6}, "resource_costs": {"sustenance": 4, "emberlight": 2}},
    {"bloodline_key": "deepwell", "key": "frost_slingers", "name": "Frost Slingers", "tier": "support",
     "ability_key": "chill", "stats": {"attack": 3, "defense": 3, "range": True},
     "resource_costs": {"sustenance": 5, "emberlight": 4}},
    {"bloodline_key": "deepwell", "key": "glacial_wardens", "name": "Glacial Wardens", "tier": "signature",
     "ability_key": "bulwark", "stats": {"attack": 4, "defense": 12},
     "resource_costs": {"everfrost": 6, "sustenance": 5}},

    # --- Wardens ---
    {"bloodline_key": "wardens", "key": "pathfinders", "name": "Pathfinders", "tier": "basic",
     "ability_key": None, "stats": {"attack": 4, "defense": 4}, "resource_costs": {"sustenance": 4, "emberlight": 2}},
    {"bloodline_key": "wardens", "key": "seers", "name": "Seers", "tier": "support",
     "ability_key": "foresight", "stats": {"attack": 2, "defense": 2, "scout": True},
     "resource_costs": {"sustenance": 4, "emberlight": 5}},
    {"bloodline_key": "wardens", "key": "oracle_vanguard", "name": "Oracle Vanguard", "tier": "signature",
     "ability_key": "premonition_strike", "stats": {"attack": 6, "defense": 6},
     "resource_costs": {"farsight": 6, "emberlight": 6}},

    # --- Driftborn ---
    {"bloodline_key": "driftborn", "key": "skirmishers", "name": "Skirmishers", "tier": "basic",
     "ability_key": None, "stats": {"attack": 5, "defense": 1, "speed": "fast"},
     "resource_costs": {"sustenance": 4, "emberlight": 2}},
    {"bloodline_key": "driftborn", "key": "windriders", "name": "Windriders", "tier": "support",
     "ability_key": "hit_and_run", "stats": {"attack": 5, "defense": 2, "speed": "fast"},
     "resource_costs": {"sustenance": 5, "emberlight": 4}},
    {"bloodline_key": "driftborn", "key": "stormrunners", "name": "Stormrunners", "tier": "signature",
     "ability_key": "flash_march", "stats": {"attack": 8, "defense": 2, "speed": "very_fast"},
     "resource_costs": {"galewisp": 6, "scrap": 5}},

    # --- Emberwrights ---
    {"bloodline_key": "emberwrights", "key": "artisans_at_arms", "name": "Artisans-at-arms", "tier": "basic",
     "ability_key": None, "stats": {"attack": 3, "defense": 3}, "resource_costs": {"sustenance": 3, "emberlight": 2}},
    {"bloodline_key": "emberwrights", "key": "siege_engineers", "name": "Siege Engineers", "tier": "support",
     "ability_key": "breach", "stats": {"attack": 6, "defense": 2, "vs_fortification_bonus": True},
     "resource_costs": {"sustenance": 5, "scrap": 5}},
    {"bloodline_key": "emberwrights", "key": "forgeguard", "name": "Forgeguard", "tier": "signature",
     "ability_key": "aegis_core", "stats": {"attack": 5, "defense": 8, "adjacent_defense_aura": True},
     "resource_costs": {"sparkstone": 6, "emberlight": 6}},
]
