"""Count identifiable room labels in raster floor plans using local, oriented OCR."""

import concurrent.futures
import csv
import functools
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata

if __package__:
    from . import scan_room_labels, scan_storeys
else:
    import scan_room_labels
    import scan_storeys


# Apple's framework supplies OCR and EXIF orientation handling without Python packages.
# The image file is private to the invocation. Orientation transforms are inverted below.
VISION_SCRIPT = """
ObjC.import('Vision');
ObjC.import('Foundation');
function run(args) {
    const request = $.VNRecognizeTextRequest.alloc.init;
    request.recognitionLevel = 0;
    request.usesLanguageCorrection = false;
    request.minimumTextHeight = 0.003;
    if (args[2] === 'sv') request.recognitionLanguages = ['sv-SE', 'en-US'];
    const requests = $.NSMutableArray.alloc.init;
    requests.addObject(request);
    const handler = $.VNImageRequestHandler.alloc.initWithURLOrientationOptions(
        $.NSURL.fileURLWithPath(args[0]), Number(args[1]), $.NSDictionary.dictionary);
    if (!handler.performRequestsError(requests, null)) throw Error('Vision OCR failed');
    const words = [];
    for (let i = 0; i < request.results.count; i++) {
        const obs = request.results.objectAtIndex(i);
        const candidate = obs.topCandidates(1).firstObject;
        const b = obs.boundingBox;
        words.push({text: ObjC.unwrap(candidate.string), confidence: Number(candidate.confidence),
                    box: [1000*b.origin.x, 1000*(1-b.origin.y-b.size.height),
                          1000*(b.origin.x+b.size.width), 1000*(1-b.origin.y)]});
    }
    return JSON.stringify(words);
}
"""

ROOMS = {
    "bedroom": {"MH", "MAKUUH", "MAKUUHUONE", "SOVRUM", "SOVR", "BEDROOM"},
    "kitchen": {"K", "KK", "KT", "KTT", "TPK", "TUPAK", "KEITTIÖ", "KEITTIÖTILA",
                "KEITTOKOMERO", "AVOKEITTIÖ", "TUPAKEITTIÖ", "APUKEITTIÖ", "KÖK", "KÖKET",
                "KOKVRÅ", "PENTRY", "KITCHEN", "KITCHENETTE"},
    "washroom": {"KPH", "KH", "PH", "PSH", "SH", "PESUH", "PESUHUONE", "KYLPYH",
                 "KYLPYHUONE", "SUIHKUH", "SUIHKUHUONE", "BAD", "BADRUM", "DUSCHRUM",
                 "BATHROOM", "WASHROOM"},
    "wc": {"WC", "W.C", "ERILLISWC", "VESSA", "TOALETT", "TOILET"},
    "sauna": {"S", "SA", "SAUNA", "BASTU"},
    "balcony": {"PARV", "PARVEKE", "PARVEK", "PARV.", "BALKONG", "BALK", "BALCONY"},
    "other": {"RUOKAILU","RUOKAILUTILA","MATSAL","DINING ROOM","OH", "OLOHUONE", "ET", "ETEINEN", "VH", "VAATEHUONE", "KHH", "KODINHOITOHUONE",
              "RT", "RUOK", "AULA", "TK", "TH", "AH", "ALKOVI", "ALK", "TERASSI", "KUISTI", "VAR",
              "VARASTO", "VARDAGSRUM", "HALL", "KLK", "KLÄDKAMMARE", "TVÄTTSTUGA", "ENTRÉ"},
}
GLYPHS = str.maketrans("АВЕКМНОРСТХІ", "ABEKMHOPCTXI")
TITLES = re.compile(r"(?<![A-Z0-9])(\d{1,2})\s*H\s*\+\s*"
                    r"(?:ALK\.?\s*\+\s*)?(TPK|KK|KT|K)(?:\s*\+\s*(S|SAUNA))?(?=$|[\s,;:()\d])")


def letters(text):
    text = unicodedata.normalize("NFKC", text).upper().translate(GLYPHS)
    return text.strip(" .,:;|!_~")


# Require a complete, affirmative declaration of the count or absence. Marketing prose
# about another apartment, optional equipment or refurbishment must never imply zero.
NO_SAUNA = re.compile(
    r"(?:SAUNATON ASUNTO|ASUNNOSSA EI OLE SAUNAA|ASUNTO ILMAN SAUNAA|"
    r"LÄGENHET UTAN BASTU|LÄGENHETEN HAR INGEN BASTU|"
    r"THIS APARTMENT HAS NO SAUNA|APARTMENT WITHOUT A SAUNA|"
    r"(?:SAUNAT|BASTUR|SAUNAS)\s*:\s*0(?:\s+KPL)?)"
)
DESIGNATION = re.compile(
    r"(?:[A-Z]\s*\d{1,3}\s*[-–:]\s*)?"
    r"(?P<type>\d{1,2}\s*H\s*\+\s*(?:ALK\.?\s*\+\s*)?"
    r"(?:TPK|KK|KT|K)(?:\s*\+\s*(?:SAUNA|S))?)"
    r"(?:\s+\d+(?:[,.]\d+)?\s*M(?:2|²|[?'’])?)?"
)


def _label(text):
    cleaned = letters(text)
    if TITLES.search(cleaned):
        return set()
    cleaned = re.sub(r"\s+\d+(?:[,.]\d+)?\s*M(?:2|['’])?.*$", "", cleaned)
    cleaned = re.sub(r"^(MH|WC|SOVRUM)\s*[- ]?\d{1,2}$", r"\1", cleaned)
    cleaned = re.sub(r"^(?:LASITETTU|LAS\.?|INGLASAD|GLAZED)\s+","",cleaned)
    # Compound room labels combine functions in one space; a WC in the bathroom is not separate.
    parts = re.split(r"\s*[+/&]\s*|\s+(?:JA|OCH|AND)\s+",cleaned)
    if parts in (["K","R"],["R","K"]):
        return {"kitchen","other"}  # keittiö + ruokailu: cooking and dining in one room
    known = {name for name, words in ROOMS.items() if any(p in words for p in parts)}
    if len(parts) > 1 and any(not any(p in words for words in ROOMS.values()) for p in parts):
        return set()
    if "washroom" in known:
        known.discard("wc")
    return known


def category(question):
    q = " ".join(question.strip().casefold().rstrip("?").split())
    forms = {
        "bedroom": ("bedrooms", "bedrooms (makuuhuone, usually marked mh)"),
        "kitchen": ("kitchens", "kitchens (including kitchenettes, open kitchens and utility kitchens)"),
        "washroom": ("bathrooms", "bathrooms or washrooms (e.g. kh, kph, ph, pesuh, sh)"),
        "wc": ("separate wc rooms", "separate wc rooms (toilet rooms marked wc)"),
        "sauna": ("saunas",),
        "balcony": ("balconies", "balconies (parveke, including glazed balconies)"),
    }
    for name, variants in forms.items():
        for noun in variants:
            prompts = {f"count the {noun}", f"how many {noun}", f"how many {noun} are on this floor plan"}
            if name == "washroom":
                prompts.add(f"how many {noun} are on this floor plan, not counting separate wc rooms")
            if q in prompts:
                return name
    return None


def _restore(box, orientation):
    x0,y0,x1,y1 = box
    if orientation in (2,3):
        x0,x1 = 1000-x1,1000-x0
    if orientation in (3,4):
        y0,y1 = 1000-y1,1000-y0
    return [min(1000,max(0,round(n,2))) for n in (x0,y0,x1,y1)]


def _vision(path, orientation, language="default"):
    run = subprocess.run(["osascript","-l","JavaScript","-e",VISION_SCRIPT,path,str(orientation),language],
                         capture_output=True, timeout=20, check=True)
    rows = json.loads(run.stdout)
    for row in rows:
        row["box"] = _restore(row["box"], orientation)
        row["engine"] = "vision"
    return rows


def _legibility(rows):
    # Readable duplex titles, room lexicon and neutral map labels distinguish correct orientation.
    count = 0
    for row in rows:
        word = letters(row["text"])
        if TITLES.search(word) or re.search(r"MITTAKAAVA|CUBICASA|KERROS|SUUNTAA-ANTAVA",word):
            count += 3
        if _label(word):
            count += 1 if len(word) < 3 else 2
    return count


def _tesseract(data, w, h):
    env = dict(os.environ,OMP_THREAD_LIMIT="1")
    langs = subprocess.run(["tesseract","--list-langs"],capture_output=True,timeout=5,env=env,check=True)
    available = set(langs.stdout.decode().splitlines())
    languages = "+".join(code for code in ("fin","swe","eng") if code in available)
    if not languages:
        return []
    call = subprocess.run(["tesseract","stdin","stdout","-l",languages,"--psm","11","tsv"],input=data,
                          capture_output=True,timeout=20,check=True,env=env)
    rows = []
    for r in csv.DictReader(io.StringIO(call.stdout.decode()),delimiter="\t",quoting=csv.QUOTE_NONE):
        if r.get("level") != "5" or not r.get("text","").strip():
            continue
        x,y,ww,hh = (int(r[k]) for k in ("left","top","width","height"))
        rows.append({"text":r["text"],"confidence":float(r["conf"])/100,"engine":"tesseract",
                     "box":[1000*x/w,1000*y/h,1000*(x+ww)/w,1000*(y+hh)/h]})
    return rows


@functools.lru_cache(maxsize=32)
def inventory(image_bytes):
    """Run OCR once per drawing across questions in this process; retain only matches in results."""
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(image_bytes)<24:
        return {}
    w,h = struct.unpack(">II", image_bytes[16:24])
    if min(w,h) <= 0 or w*h>35_000_000:
        return {}
    passes = []
    orientation = 1
    complete = False
    if sys.platform == "darwin" and shutil.which("osascript"):
        with tempfile.NamedTemporaryFile(suffix=".png") as image:
            image.write(image_bytes)
            image.flush()
            try:
                # Mirrored or upside-down marketing plans are frequent. Never sum passes.
                oriented = [_vision(image.name,1)]
                if _legibility(oriented[0]) < 8:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
                        oriented.extend(workers.map(lambda o: _vision(image.name,o),(2,3,4)))
                best = max(range(len(oriented)), key=lambda i: _legibility(oriented[i]))
                passes = oriented[best]
                orientation = best+1
                if _legibility(passes) < 12:
                    alternate = _vision(image.name, best+1, "sv")
                    passes = passes + alternate
                complete = True
                if best != 0:
                    return dict(_summarize(passes, image_bytes), orientation=orientation, vision=True)
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
    if shutil.which("tesseract"):
        try:
            passes = passes + _tesseract(image_bytes,w,h)
        except (OSError,subprocess.SubprocessError,ValueError):
            pass
    # The winning reading direction is reused when a room is read again at a larger scale.
    # A reader that reasons from the absence of a label must know the sheet pass completed.
    return dict(_summarize(passes, image_bytes), orientation=orientation, vision=complete)


def _same(a,b):
    x,y,x1,y1 = a
    u,v,u1,v1 = b
    inter = max(0,min(x1,u1)-max(x,u))*max(0,min(y1,v1)-max(y,v))
    smaller = min((x1-x)*(y1-y),(u1-u)*(v1-v))
    return smaller > 0 and inter/smaller >= .48


def _summarize(rows, image_bytes=None):
    labels = {n:[] for n in ROOMS}
    titles = []
    floor_markers = set()
    possible_wc = []
    explicit_no_sauna = []
    for row in sorted(rows,key=lambda r: (r.get("engine")=="vision",r["confidence"]),reverse=True):
        box = row["box"]
        if len(box)!=4 or not all(math.isfinite(x) for x in box) or box[0]>=box[2] or box[1]>=box[3]:
            continue
        text = row["text"]
        token = letters(text)
        if re.fullmatch(r"(?:ALA|YLÄ|KELLARI|ULLAKKO)KERTA|(?:POHJA|KELLARI|ULLAKKO)KERROS|[1-9]\.?\s*KERROS",token):
            floor_markers.add(token)
        if token in {"WG","W0","WС"}:
            possible_wc.append(box)
        if NO_SAUNA.fullmatch(token) and row["confidence"] >= .75:
            if not any(_same(box,r["box"]) for r in explicit_no_sauna):
                explicit_no_sauna.append({"label":text,"box":box})
        designation = DESIGNATION.fullmatch(token)
        if designation and row.get("engine") == "vision" and row["confidence"] >= .5:
            unit = designation["type"]
            has_sauna = bool(re.search(r"\+\s*(?:S|SAUNA)$",unit))
            title = {"label":unit,"box":box,"kitchen":1,"sauna":int(has_sauna)}
            if not any(_same(box,t["box"]) for t in titles):
                titles.append(title)
        if row["confidence"] < (.47 if row.get("engine")=="vision" else .70):
            continue
        for name in _label(text):
            if len(letters(text)) == 1 and row.get("engine") != "vision":
                continue
            evidence = labels[name]
            if not any(_same(box,r["box"]) for r in evidence):
                evidence.append({"label":text,"box":box})
    if image_bytes is not None:
        labels["bedroom"] = scan_room_labels.enclosed_bedrooms(image_bytes, labels["bedroom"])
    return {"labels":labels,"titles":titles,"floor_markers":sorted(floor_markers),"possible_wc":possible_wc,
            "explicit_no_sauna":explicit_no_sauna,"storeys":scan_storeys.captions(rows)}


def from_inventory(inv, name):
    if not inv or name not in ROOMS:
        return None
    labels, titles = inv["labels"], inv["titles"]
    evidence = labels[name]
    recognized = sum(map(len,labels.values()))
    if name == "bedroom" and evidence:
        numbers = [re.fullmatch(r"(?:MH|SOVRUM)\s*[- ]?(\d{1,2})",letters(r["label"])) for r in evidence]
        numbers = {int(m[1]) for m in numbers if m}
        if numbers and max(numbers) > len(evidence):
            return None  # a visible MH3 and only two labels leave a numbered bedroom unaccounted for
    if (name == "bedroom" and not evidence and len(titles) == 1
            and not inv.get("floor_markers") and not inv.get("storeys")):
        title = titles[0]
        if re.fullmatch(r"1\s*H\s*\+\s*(?:K|KK|KT|TPK)",letters(title["label"])):
            living = [r for r in labels["other"] if any(
                part in {"OH","OLOHUONE","VARDAGSRUM"} for part in re.split(r"\s*[+/&]\s*",letters(r["label"])))]
            if len(living) == 1:
                return {"status":"answered","answer":0,"evidence":[],"method":"local_room_labels",
                        "coordinate_system":"xyxy_top_left_0_to_1000",
                        "reason":"The apartment has one habitable room, explicitly labelled as its living room.",
                        "coverage_evidence":[{"label":"Apartment designation "+title["label"],"box":title["box"]},living[0]]}
    if name == "wc" and evidence:
        if len(evidence) == 1 and (inv.get("floor_markers") or recognized < 5):
            return None
        if any(not any(_same(b,e["box"]) for e in evidence) for b in inv.get("possible_wc",())):
            return None
    if name == "kitchen" and len(evidence)>1 and any(
            len(re.split(r"[+/&]",e["label"]))>1 for e in evidence):
        return None  # mixed-use room label plus a kitchen sub-area label may describe one kitchen
    if name == "sauna" and not evidence and len(inv.get("explicit_no_sauna",())) == 1:
        if (recognized >= 3 and not inv.get("floor_markers") and len(titles) <= 1
                and not any(t["sauna"] for t in titles)):
            return {"status":"answered","answer":0,"evidence":[],"method":"local_room_labels",
                    "coordinate_system":"xyxy_top_left_0_to_1000",
                    "reason":"An explicit source label states that the apartment has no sauna.",
                    "coverage_evidence":inv["explicit_no_sauna"]}
    # A declared apartment type is an explicit positive for its kitchen and optional sauna.
    # One room label alone is insufficient context to establish that it belongs to a plan.
    if (len(titles)==1 and name in ("kitchen","sauna") and titles[0][name] == 1 and len(evidence) <= 1
            and (recognized >= 2 or name == "sauna")):
        evidence = evidence or [{"label":"Apartment designation "+titles[0]["label"],"box":titles[0]["box"]}]
    elif not evidence or recognized < 3 or len([k for k,v in labels.items() if v]) < 2:
        return None
    return {"status":"answered","answer":len(evidence),"evidence":evidence,
            "method":"local_room_labels","coordinate_system":"xyxy_top_left_0_to_1000"}


def predict(image_bytes, question):
    name = category(question)
    return from_inventory(inventory(image_bytes),name) if name else None
