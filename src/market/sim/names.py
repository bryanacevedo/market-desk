"""Invented names. Every company, person and city label here is made up; domains end in .example."""
from __future__ import annotations

START = ["Al", "Bri", "Cal", "Dor", "El", "Fen", "Gal", "Hal", "Ir", "Jun", "Kel", "Lum", "Mar", "Nor", "Ol", "Pel",
         "Quin", "Ros", "Sel", "Tor", "Ul", "Val", "Wil", "Xan", "Yar", "Zen", "Ash", "Bel", "Cor", "Dav", "Ev", "Fal",
         "Gren", "Hav", "Isk", "Jas", "Kor", "Lin", "Mer", "Nev", "Orl", "Pr", "Ral", "Sor", "Tal", "Ven", "Wyn", "Ard"]
MID = ["a", "e", "i", "o", "u", "ae", "io", "ar", "en", "or", "il", "an", "er", "ol", "ul", "ir"]
END = ["ck", "dor", "fin", "gate", "ham", "ix", "ley", "mont", "nex", "pas", "quist", "rin", "son", "tra", "vel",
       "wick", "yard", "zo", "bury", "crest", "field", "ford", "line", "more", "path", "stone", "wood", "worth", "ra", "n"]
SUFFIX = {
    "Software": ["Cloud", "Software", "Labs", "Apps", "HQ", "Works"],
    "Fintech": ["Pay", "Capital", "Lend", "Finance", "Money", "Ledger"],
    "Data infrastructure": ["Data", "Stream", "Graph", "Warehouse", "Lake", "Pipe"],
    "Developer tools": ["Dev", "Build", "Code", "Stack", "Deploy", "Ops"],
    "Marketplaces": ["Market", "Exchange", "Bazaar", "Trade", "Hub", "Mart"],
    "Healthcare software": ["Health", "Care", "Clinic", "Med", "Rx", "Vitals"],
    "IT services": ["Consulting", "Partners", "IT", "Services", "Solutions", "Group"],
    "Agencies": ["Studio", "Agency", "Creative", "Collective", "Media Lab", "Works"],
    "E-commerce": ["Shop", "Store", "Goods", "Supply", "Direct", "Co"],
    "Manufacturing": ["Industries", "Manufacturing", "Fabrication", "Components", "Metals", "Machines"],
    "Education": ["Academy", "Learning", "Institute", "School", "Tutors", "Campus"],
    "Government": ["Agency", "Authority", "Council", "Bureau", "Office", "Board"],
    "Media": ["Media", "Press", "Broadcast", "Pictures", "Network", "Daily"],
    "Logistics": ["Freight", "Logistics", "Cargo", "Haul", "Shipping", "Transit"],
}

FIRST = ["Marta", "Jonas", "Aiko", "Bruno", "Celine", "Dmitri", "Esther", "Farid", "Greta", "Hugo", "Ines", "Jakob",
         "Kira", "Leon", "Mireille", "Niko", "Odile", "Pavel", "Quentin", "Rosa", "Stefan", "Tamsin", "Ulrich", "Vera",
         "Wendell", "Ximena", "Yusuf", "Zora", "Anders", "Beatriz", "Cormac", "Delphine", "Emeka", "Fiona", "Gideon",
         "Helga", "Ivo", "Jolene", "Kwame", "Lotte", "Matteo", "Nell", "Oskar", "Petra", "Rafael", "Saskia", "Thiago",
         "Una", "Viktor", "Wanda", "Ayla", "Bastian", "Clio", "Dario", "Elif", "Florian", "Gemma", "Hamza", "Isolde"]
LAST = ["Klein", "Albrecht", "Tanaka", "Moreau", "Varga", "Lindgren", "Okonjo", "Castellano", "Brandt", "Sato",
        "Fontaine", "Nyberg", "Haddow", "Pereira", "Kowalczyk", "Dunmore", "Ferreira", "Gallagher", "Hartmann",
        "Ishikawa", "Jansen", "Kaplan", "Lombardi", "Marchetti", "Novak", "Orlov", "Pacheco", "Quinlan", "Rasmussen",
        "Sandoval", "Toivonen", "Ueda", "Vasquez", "Wexler", "Yilmaz", "Zielinski", "Abernathy", "Bergstrom",
        "Calloway", "Delacroix", "Eriksen", "Fairbairn", "Grunwald", "Holloway", "Iversen", "Jaramillo", "Kessler"]

CITIES = {
    "US": ["Brookhaven City", "Pine Harbor", "Westmere", "Calder Falls", "Ridgemont", "Larkspur Bay", "Easton Mill",
           "Silver Lake City", "Granite Point", "Maple Crossing"],
    "CA": ["Northgate", "Lakeshore", "Pinecrest"],
    "MX": ["Valle Verde", "Puerto Claro"],
    "GB": ["Ashford Green", "Kingsbridge", "Marlow Heath", "Thornbury"],
    "IE": ["Glenmore"],
    "DE": ["Lindenfeld", "Rheinau", "Waldheim"],
    "AT": ["Seetal"],
    "CH": ["Bergli"],
    "FR": ["Belleville-sur-Mer", "Montclair"],
    "NL": ["Havenstad", "Dijkveld"],
    "BE": ["Brugmont"],
    "SE": ["Sjoberg"], "DK": ["Havnby"], "NO": ["Fjordvik"], "FI": ["Jarvela"],
    "ES": ["Costa Alta", "Valdemar"], "IT": ["Montealto"], "PT": ["Ribamar"],
    "BR": ["Porto Novo", "Serra Clara"], "AR": ["Rio Plata"],
    "AU": ["Southbank", "Coral Bay"], "IN": ["Navapur", "Lakshmi Nagar"], "SG": ["Marina Point"],
}
