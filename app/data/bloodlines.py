"""Static bloodline reference data. Seed these five rows once via a migration or a
seed script — see app/models/player.py:Bloodline. Matches Section 2 of the design doc.
"""

BLOODLINES = [
    {
        "key": "kindled",
        "name": "Kindled",
        "resonance_type": "emberdust",
        "strength_desc": "Fast troop training, strong attack power",
        "weakness_desc": "Weak garrison defense, high upkeep",
    },
    {
        "key": "deepwell",
        "name": "Deepwell",
        "resonance_type": "everfrost",
        "strength_desc": "Strong defense, large Emberlight storage",
        "weakness_desc": "Slow expansion / build speed",
    },
    {
        "key": "wardens",
        "name": "Wardens",
        "resonance_type": "farsight",
        "strength_desc": "Long scouting range, early attack warning, Circle coordination bonus",
        "weakness_desc": "Weak raw combat power",
    },
    {
        "key": "driftborn",
        "name": "Driftborn",
        "resonance_type": "galewisp",
        "strength_desc": "Fast unit travel, first-strike edge on contested tiles",
        "weakness_desc": "Weak garrisons once ground is taken",
    },
    {
        "key": "emberwrights",
        "name": "Emberwrights",
        "resonance_type": "sparkstone",
        "strength_desc": "Cheap/fast buildings, passive fortification bonus",
        "weakness_desc": "Slow troop output",
    },
]

# Self-mitigation tech/building per bloodline (Section on self-mitigation paths).
# Each one trades part of the bloodline's own strength/resource to reduce its weakness —
# never a flat free fix, and never requires another bloodline to unlock.
SELF_MITIGATION = {
    "kindled": {
        "key": "ashwall_forges",
        "name": "Ashwall Forges",
        "effect": "raises garrison strength",
        "cost": "slightly reduces troop-training speed bonus per forge built",
    },
    "deepwell": {
        "key": "thawrunners",
        "name": "Thawrunners",
        "effect": "speeds up Hold founding and build times",
        "cost": "reduces Emberlight storage capacity",
    },
    "wardens": {
        "key": "vanguard_discipline",
        "name": "Vanguard Discipline",
        "effect": "raises combat power",
        "cost": "consumes Farsight resonance (their scouting/Circle fuel)",
    },
    "driftborn": {
        "key": "anchor_stakes",
        "name": "Anchor Stakes",
        "effect": "stabilizes garrisons on a captured tile",
        "cost": "reduces travel speed on that tile's army lane",
    },
    "emberwrights": {
        "key": "foundry_lines",
        "name": "Foundry Lines",
        "effect": "speeds up troop training",
        "cost": "raises building costs elsewhere",
    },
}
