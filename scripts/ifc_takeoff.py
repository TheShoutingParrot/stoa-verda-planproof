"""Read native IFC STEP entity counts and assigned space quantities without a BIM runtime."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


CLASSES = {
    "doors": {"IFCDOOR", "IFCDOORSTANDARDCASE"},
    "windows": {"IFCWINDOW", "IFCWINDOWSTANDARDCASE"},
    "walls": {"IFCWALL", "IFCWALLSTANDARDCASE", "IFCWALLELEMENTEDCASE"},
    "rooms (spaces)": {"IFCSPACE"},
    "beams": {"IFCBEAM", "IFCBEAMSTANDARDCASE"},
    "columns": {"IFCCOLUMN", "IFCCOLUMNSTANDARDCASE"},
    "stairs": {"IFCSTAIR"},
    "sanitary fixtures": {"IFCSANITARYTERMINAL"},
    "light fixtures": {"IFCLIGHTFIXTURE"},
}
TYPE_CLASSES = {"IFCSANITARYTERMINALTYPE": "sanitary fixtures", "IFCLIGHTFIXTURETYPE": "light fixtures"}
OCCURRENCES = {kind: name for name, kinds in CLASSES.items() for kind in kinds}
RELATIONS = {
    "IFCRELAGGREGATES", "IFCRELNESTS", "IFCRELCONTAINEDINSPATIALSTRUCTURE",
    "IFCRELDEFINESBYTYPE", "IFCRELDEFINESBYPROPERTIES",
}
UNITS = {"IFCUNITASSIGNMENT", "IFCSIUNIT", "IFCCONVERSIONBASEDUNIT", "IFCMEASUREWITHUNIT"}
RETAIN = set(OCCURRENCES) | set(TYPE_CLASSES) | RELATIONS | UNITS | {
    "IFCSPACE", "IFCBUILDINGSTOREY", "IFCFLOWTERMINAL", "IFCPROJECT",
    "IFCQUANTITYAREA", "IFCPROPERTYSINGLEVALUE", "IFCPROPERTYSET", "IFCELEMENTQUANTITY",
}
PREFIXES = dict(zip(
    "EXA PETA TERA GIGA MEGA KILO HECTO DECA DECI CENTI MILLI MICRO NANO PICO FEMTO ATTO".split(),
    (18, 15, 12, 9, 6, 3, 2, 1, -1, -2, -3, -6, -9, -12, -15, -18)
))
# STEP strings can contain commas, semicolons, doubled quotes and comments as literal text.
BOUNDARY = re.compile(rb"'(?:[^']|'')*'|/\*.*?\*/|;", re.S)
HEAD = re.compile(rb"\s*(?:/\*.*?\*/\s*)*#(\d+)\s*=\s*(IFC[\w]+)\s*\(", re.S | re.I)
SCHEMA = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", re.I)
ATTRIBUTE_TOKEN = re.compile(r"'(?:[^']|'')*'|/\*.*?\*/|[(),]", re.S)
COMMENT_OR_STRING = re.compile(r"'(?:[^']|'')*'|/\*.*?\*/", re.S)
STEP_UNICODE = re.compile(r"\\X([24])\\([a-fA-F0-9]+)\\X0\\")
REFERENCE = re.compile(r"#(\d+)")
AREA_NAMES = {"netfloorarea", "netarea"}
GEOMETRY = {
    "IFCPRODUCTDEFINITIONSHAPE", "IFCSHAPEREPRESENTATION", "IFCEXTRUDEDAREASOLID",
    "IFCRECTANGLEPROFILEDEF", "IFCARBITRARYCLOSEDPROFILEDEF", "IFCARBITRARYPROFILEDEFWITHVOIDS",
    "IFCPOLYLINE", "IFCCARTESIANPOINT", "IFCDIRECTION", "IFCAXIS2PLACEMENT3D",
    "IFCFACEBASEDSURFACEMODEL", "IFCCONNECTEDFACESET", "IFCFACE",
    "IFCFACEBOUND", "IFCFACEOUTERBOUND", "IFCPOLYLOOP",
}
NUMERIC = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:E[+-]?\d+)?"
MEASURE = re.compile(rf"(?:IFC\w+MEASURE\(({NUMERIC})\)|({NUMERIC}))", re.I)


def label(value):
    if len(value) < 2 or not value.startswith("'") or not value.endswith("'"):
        return ""
    def decode(match):
        try:
            return bytes.fromhex(match[2]).decode("utf-16-be" if match[1] == "2" else "utf-32-be")
        except (ValueError, UnicodeError):
            return match[0]
    return STEP_UNICODE.sub(decode, value[1:-1].replace("''", "'"))


def key(s):
    return " ".join(s.casefold().split())


def ref(s):
    match = REFERENCE.fullmatch(s)
    return int(match[1]) if match else None


def refs(s):
    return tuple(int(v) for v in REFERENCE.findall(s))


def attributes(content):
    if "/*" in content:
        content = COMMENT_OR_STRING.sub(lambda m: " " if m[0].startswith("/*") else m[0], content)
    depth = last = 0
    parts = []
    for match in ATTRIBUTE_TOKEN.finditer(content):
        token = match[0]
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif token == "," and depth == 0:
            parts.append(content[last:match.start()].strip())
            last = match.end()
    parts.append(content[last:].strip())
    return parts


@dataclass(slots=True)
class Record:
    id: int
    kind: str
    fields: list
    source: str


def records(raw, geometry):
    start = 0
    for boundary in BOUNDARY.finditer(raw):
        if raw[boundary.start()] != 59:  # semicolon outside strings and comments
            continue
        end = boundary.start()
        head = HEAD.match(raw, start, end)
        start = boundary.end()
        if not head:
            continue
        kind = head[2].decode().upper()
        if kind in GEOMETRY:
            geometry.offsets[int(head[1])] = (head.start(1)-1, end+1)
        if kind not in RETAIN:
            continue
        body = raw[head.end():end].rstrip()
        if not body.endswith(b")"):
            raise ValueError("Invalid IFC STEP declaration")
        fields = attributes(body[:-1].decode("utf-8", errors="replace"))
        if kind in {"IFCPROPERTYSINGLEVALUE", "IFCQUANTITYAREA"} and key(label(fields[0])).replace(" ", "") not in AREA_NAMES:
            continue
        source = raw[head.start(1)-1:min(end+1,head.start(1)+999)].decode("utf-8", errors="replace")
        yield Record(int(head[1]), kind, fields, source)


def numeric(s):
    m = MEASURE.fullmatch(s)
    if m:
        value = float(m[1] or m[2])
        if math.isfinite(value):
            return value
    return None


def unit_scale(unit_id, declarations, dimension="AREA", visited=frozenset()):
    e = declarations.get(unit_id)
    if not e or unit_id in visited:
        return None
    f = e.fields
    unit_name = ".SQUARE_METRE." if dimension == "AREA" else ".METRE."
    unit_type = f".{dimension}UNIT."
    if e.kind == "IFCSIUNIT" and f[1].upper() == unit_type and f[3].upper() == unit_name:
        if f[2] == "$":
            return 1.
        prefix = f[2].upper().strip(".")
        if prefix in PREFIXES:
            return 10. ** ((2 if dimension == "AREA" else 1) * PREFIXES[prefix])
    if e.kind == "IFCCONVERSIONBASEDUNIT" and f[1].upper() == unit_type:
        factor = declarations.get(ref(f[3]))
        if factor and factor.kind == "IFCMEASUREWITHUNIT":
            scale = unit_scale(ref(factor.fields[1]), declarations, dimension, visited | {unit_id})
            multiplier = numeric(factor.fields[0])
            if scale and multiplier and multiplier > 0:
                return scale * multiplier
    return None


@dataclass(slots=True)
class Area:
    value: float
    quantity: Record | None
    group_id: int | None
    relation_id: int | None
    unit_id: int
    geometry_ids: tuple = ()
    geometry_source: str | None = None


@dataclass(slots=True)
class Product:
    record: Record
    category: str
    storey: str
    storey_id: int | None
    containment: tuple
    type_relation: int | None
    type_id: int | None
    area: Area | None

    @property
    def room_label(self):
        short, long = label(self.record.fields[2]), label(self.record.fields[7])
        return f"{long} ({short})" if short and long else long or short


@dataclass(slots=True)
class Model:
    schema: str
    storeys: list
    levels: dict
    products: dict
    names: set


def catalog_titles(raw: bytes, *, with_attribution=False):
    """Read official raw-model titles or full credits from the sponsor's attribution table."""
    result = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        cells = line.strip().split("|")
        if len(cells) != 7 or cells[0] or cells[-1]:
            continue
        filename, title, license_name, credit, source_url = (c.strip() for c in cells[1:6])
        if filename.lower().endswith(".ifc") and filename not in result:
            result[filename] = dict(work=title, license=license_name, credit=credit, sourceUrl=source_url
                                    ) if with_attribution else title
    return result


def declared_area(room_id, assigned, declarations, project_unit):
    candidates = defaultdict(list)
    for gid, rid in assigned.get(room_id, ()):
        group = declarations.get(gid)
        if not group or group.kind not in {"IFCELEMENTQUANTITY","IFCPROPERTYSET"}:
            continue
        for qid in refs(group.fields[-1]):
            q = declarations.get(qid)
            if not q or q.kind not in {"IFCQUANTITYAREA","IFCPROPERTYSINGLEVALUE"}:
                continue
            name = key(label(q.fields[0])).replace(" ", "")
            if name not in AREA_NAMES:
                continue
            rank = 0 if name == "netfloorarea" else 1
            quantity = q.kind == "IFCQUANTITYAREA"
            unit_field = q.fields[2 if quantity else 3]
            unit_id = project_unit if unit_field == "$" else ref(unit_field)
            scale = unit_scale(unit_id, declarations)
            value = numeric(q.fields[3 if quantity else 2])
            if value is not None and value >= 0 and scale and math.isfinite(value * scale):
                candidates[rank].append(Area(value*scale, q, gid, rid, unit_id))
    if candidates:
        best = candidates[min(candidates)]
        if all(math.isclose(best[0].value, candidate.value, rel_tol=1e-8, abs_tol=1e-9) for candidate in best):
            return best[0]
    return None


class Geometry:
    """Read shape records on demand; the index and original bytes expire after building the model."""

    def __init__(self, raw):
        self.raw = raw
        self.offsets = {}
        self.cache = {}

    def get(self, eid, *kinds):
        if eid not in self.offsets:
            return None
        if eid not in self.cache:
            start, end = self.offsets[eid]
            head = HEAD.match(self.raw, start, end)
            body = self.raw[head.end():end-1].rstrip()
            if not body.endswith(b")"):
                return None
            self.cache[eid] = Record(eid, head[2].decode().upper(),
                                     attributes(body[:-1].decode("utf-8", errors="replace")),
                                     self.raw[start:min(start+1000,end)].decode("utf-8", errors="replace"))
        record = self.cache[eid]
        return record if record.kind in kinds else None

    def coordinates(self, eid, kind="IFCCARTESIANPOINT"):
        p = self.get(eid, kind)
        if p:
            return tuple(numeric(s.strip()) for s in p.fields[0].strip("()").split(","))
        return ()

    def vertical(self, direction):
        vector = self.coordinates(direction, "IFCDIRECTION")
        return len(vector) == 3 and all(v is not None for v in vector) and abs(vector[2]) > 0 and (
            math.hypot(vector[0],vector[1]) < abs(vector[2])*1e-8)

    def loop(self, eid, kind, require_closure=False):
        curve = self.get(eid, kind)
        if not curve:
            return None
        points = [self.coordinates(i) for i in refs(curve.fields[0])]
        if len(points) < 3 or any(len(p)<2 or None in p for p in points):
            return None
        if require_closure and points[0] != points[-1]:
            return None
        return points

    @staticmethod
    def shoelace(points):
        # Shift to the first vertex for accuracy in models with large survey coordinates.
        x0,y0 = points[0][:2]
        return abs(math.fsum((a[0]-x0)*(b[1]-y0) - (b[0]-x0)*(a[1]-y0)
                             for a,b in zip(points, points[1:]+points[:1])))/2

    def horizontal_sweep(self, solid, placement):
        # A vertical profile swept perpendicularly in a horizontal direction projects to a
        # rectangle: horizontal span of its outer loop times extrusion depth.
        normal = self.coordinates(ref(placement.fields[1]), "IFCDIRECTION")
        if len(normal) != 3 or None in normal or not math.isclose(normal[2],0.,abs_tol=1e-10):
            return None
        normal_size = math.hypot(normal[0],normal[1])
        if not normal_size:
            return None
        z = (normal[0]/normal_size, normal[1]/normal_size, 0.)
        x = self.coordinates(ref(placement.fields[2]), "IFCDIRECTION")
        if len(x) != 3 or None in x:
            return None
        # IfcAxis2Placement3D projects RefDirection into the plane normal to Axis.
        dot = math.fsum(a*b for a,b in zip(x,z))
        x = tuple(x[i]-z[i]*dot for i in range(3))
        magnitude = math.hypot(*x)
        if not magnitude:
            return None
        x = tuple(v/magnitude for v in x)
        # Horizontal unit vector lying in the swept profile's vertical plane.
        horizontal = (-z[1],z[0])
        local_u = x[0]*horizontal[0]+x[1]*horizontal[1]
        local_v = -x[2]
        depth = numeric(solid.fields[3])
        profile = self.get(ref(solid.fields[0]),"IFCARBITRARYCLOSEDPROFILEDEF")
        if not profile or profile.fields[0] != ".AREA." or depth is None or depth <= 0:
            return None
        polyline = ref(profile.fields[2])
        points = self.loop(polyline,"IFCPOLYLINE",require_closure=True)
        if not points or any(len(p) != 2 for p in points):
            return None
        along_floor = [u*local_u+v*local_v for u,v in points]
        return (max(along_floor)-min(along_floor))*depth, [profile.id,polyline,placement.id], profile.source

    def swept(self, solid):
        # The local extrusion and profile-normal axes must both be vertical.
        placement = self.get(ref(solid.fields[1]),"IFCAXIS2PLACEMENT3D")
        if not self.vertical(ref(solid.fields[2])) or (solid.fields[1] != "$" and not placement):
            return None
        if placement and placement.fields[1] != "$" and not self.vertical(ref(placement.fields[1])):
            return self.horizontal_sweep(solid, placement)
        profile = self.get(ref(solid.fields[0]), "IFCRECTANGLEPROFILEDEF", "IFCARBITRARYCLOSEDPROFILEDEF",
                           "IFCARBITRARYPROFILEDEFWITHVOIDS")
        if not profile or profile.fields[0].upper() != ".AREA.":
            return None
        if profile.kind == "IFCRECTANGLEPROFILEDEF":
            size = [numeric(a) for a in profile.fields[3:5]]
            if len(size) != 2 or any(a is None or a <= 0 for a in size):
                return None
            return size[0]*size[1], [profile.id], profile.source
        rings = [ref(profile.fields[2])]
        if profile.kind == "IFCARBITRARYPROFILEDEFWITHVOIDS":
            rings.extend(refs(profile.fields[3]))
        areas = []
        for ring in rings:
            points = self.loop(ring, "IFCPOLYLINE", require_closure=True)
            if not points or any(len(p) != 2 for p in points):
                return None
            areas.append(self.shoelace(points))
        return areas[0]-math.fsum(areas[1:]), [profile.id]+rings, profile.source

    def surface(self, shell):
        # A single connected, faceted room body can be measured from its level bottom faces.
        connected = refs(shell.fields[0])
        if len(connected) != 1:
            return None
        face_set = self.get(connected[0],"IFCCONNECTEDFACESET")
        if not face_set:
            return None
        min_z = math.inf
        horizontal = []
        for fid in refs(face_set.fields[0]):
            face = self.get(fid, "IFCFACE")
            if not face:
                return None
            rings = []
            for bid in refs(face.fields[0]):
                bound = self.get(bid, "IFCFACEOUTERBOUND", "IFCFACEBOUND")
                if not bound:
                    return None
                loop_id = ref(bound.fields[0])
                points = self.loop(loop_id, "IFCPOLYLOOP")
                if not points or any(len(p) != 3 for p in points):
                    return None
                rings.append((bound.kind, loop_id, points))
            if not rings or sum(k == "IFCFACEOUTERBOUND" for k,_,_ in rings) != 1:
                return None
            z = [p[2] for _,_,points in rings for p in points]
            min_z = min(min_z,min(z))
            if max(z)-min(z) < 1e-8:
                area = math.fsum(self.shoelace(pts)*(1 if kind == "IFCFACEOUTERBOUND" else -1)
                                 for kind,_,pts in rings)
                horizontal.append((min(z), area, face, [ring for _,ring,_ in rings]))
        bottom = [entry for entry in horizontal if abs(entry[0]-min_z) < 1e-8]
        if not bottom:
            return None
        ids = [face_set.id] + [i for _,_,face,rings in bottom for i in [face.id,*rings]]
        return math.fsum(a for _,a,_,_ in bottom), ids, bottom[0][2].source

    def space_area(self, shape_id, length_unit, length_scale):
        shape = self.get(shape_id,"IFCPRODUCTDEFINITIONSHAPE")
        if not shape:
            return None
        reps = [self.get(i,"IFCSHAPEREPRESENTATION") for i in refs(shape.fields[2])]
        body = [r for r in reps if r and key(label(r.fields[1])) == "body"]
        if len(body) != 1:
            return None
        rep = body[0]
        items = refs(rep.fields[3])
        if len(items) != 1:
            return None  # disjointness of multiple shapes has not been established
        item = self.get(items[0],"IFCEXTRUDEDAREASOLID","IFCFACEBASEDSURFACEMODEL")
        if not item:
            return None
        measured = self.swept(item) if item.kind == "IFCEXTRUDEDAREASOLID" else self.surface(item)
        if not measured:
            return None
        area, ids, source = measured
        value = area*length_scale**2
        if not math.isfinite(value) or value <= 0:
            return None
        return Area(value, None, None, None, length_unit, (shape_id,rep.id,item.id,*ids), source)


def build_model(raw: bytes, title=None) -> Model:
    """Build a compact index from one unpacked STEP file. No archive or answer key is used."""
    schema_match = SCHEMA.search(raw[:65536])
    if not schema_match:
        raise ValueError("Missing IFC FILE_SCHEMA declaration")
    schema = schema_match[1].decode().upper()
    if not re.fullmatch(r"IFC(?:2X3|4(?:X[123])?)(?:_[A-Z0-9_]+)?", schema):
        raise ValueError(f"Unsupported IFC schema {schema}")
    geometry = Geometry(raw)
    declarations = {row.id: row for row in records(raw, geometry)}
    projects = [row for row in declarations.values() if row.kind == "IFCPROJECT"]
    if not projects:
        raise ValueError("Missing IfcProject")
    levels = {r.id: label(r.fields[2]) for r in declarations.values() if r.kind == "IFCBUILDINGSTOREY"}
    unit_refs = set()
    for project in projects:
        assignment = declarations.get(ref(project.fields[-1]))
        if assignment and assignment.kind == "IFCUNITASSIGNMENT":
            unit_refs.update(refs(assignment.fields[0]))
    area_units = [i for i in unit_refs if unit_scale(i, declarations)]
    length_units = [i for i in unit_refs if unit_scale(i, declarations, "LENGTH")]
    project_unit = area_units[0] if len(area_units) == 1 else None
    length_unit = length_units[0] if len(length_units) == 1 else None
    length_scale = unit_scale(length_unit, declarations, "LENGTH")

    parents, assigned, types = defaultdict(list), defaultdict(list), {}
    for row in declarations.values():
        f = row.fields
        if row.kind in {"IFCRELAGGREGATES","IFCRELNESTS","IFCRELCONTAINEDINSPATIALSTRUCTURE"}:
            contained = row.kind == "IFCRELCONTAINEDINSPATIALSTRUCTURE"
            owner, children = (f[5], f[4]) if contained else (f[4], f[5])
            for child in refs(children):
                parents[child].append((ref(owner),row.id))
        elif row.kind == "IFCRELDEFINESBYPROPERTIES":
            for child in refs(f[4]):
                if child in declarations and declarations[child].kind == "IFCSPACE":
                    assigned[child].extend((gid,row.id) for gid in refs(f[5]))
        elif row.kind == "IFCRELDEFINESBYTYPE":
            t = declarations.get(ref(f[5]))
            if t and t.kind in TYPE_CLASSES:
                for child in refs(f[4]):
                    types[child] = (TYPE_CLASSES[t.kind],row.id,t.id)

    def resolve_storey(eid, seen=frozenset()):
        if eid in levels:
            return [(eid,())]
        if eid in seen:
            return []
        return [(sid,(rid,)+path) for parent,rid in parents.get(eid,())
                for sid,path in resolve_storey(parent, seen | {eid})]

    products = defaultdict(list)
    for r in declarations.values():
        category = OCCURRENCES.get(r.kind)
        type_rel = type_id = None
        if r.id in types and r.kind == "IFCFLOWTERMINAL":
            category, type_rel, type_id = types[r.id]
        if not category:
            continue
        memberships = resolve_storey(r.id)
        sid, path = memberships[0] if len({s for s,_ in memberships}) == 1 else (None,())
        area = declared_area(r.id, assigned, declarations, project_unit) if category == "rooms (spaces)" else None
        if category == "rooms (spaces)" and area is None and length_scale:
            area = geometry.space_area(ref(r.fields[6]), length_unit, length_scale)
        products[category].append(Product(r, category, levels.get(sid,""), sid, path, type_rel, type_id, area))
    names = {key(label(p.fields[i])) for p in projects for i in (2,5) if label(p.fields[i])}
    if title:
        names.add(key(title))
    return Model(schema, sorted(set(levels.values())), levels, dict(products), names)


def read_model(path):
    return build_model(Path(path).read_bytes(), title=Path(path).stem)


# Categories are closed, while storey and room values must match the selected model.
CATEGORY = "|".join(re.escape(c) for c in (*CLASSES,"rooms","spaces"))
COUNT = re.compile(rf"(?:How many |Count (?:the )?)(?P<category>{CATEGORY})"
                   r"(?:(?: are there| are)? in (?:the |this )?model(?: '(?P<model>.+)')?"
                   r"|(?: are shown on the floor plan of| are (?:there )?on| on) (?P<level>.+))?", re.I)
TOTAL = re.compile(r"(?:What is the )?total net floor area of all (?:rooms(?: \(spaces\))?|spaces) on (.+)", re.I)
SINGLE = re.compile(r"(?:What is the )?net floor area of (?:the )?room (.+) on (.+)", re.I)


def unquote(value):
    if len(value) >= 2 and value[0] in {"'",'"'} and value[0] == value[-1]:
        return value[1:-1]
    return value


def evidence(p, area=False):
    r = p.record
    q = p.area if area else None
    shape = ref(r.fields[6]) if len(r.fields) > 6 else None
    return {
        "step_id": r.id, "ifc_type": r.kind, "global_id": label(r.fields[0]),
        "name": p.room_label if r.kind == "IFCSPACE" else label(r.fields[2]),
        "storey": p.storey, "storey_id": p.storey_id, "relation_ids": list(p.containment) +
        ([p.type_relation] if p.type_relation else []) + ([q.relation_id] if q and q.relation_id else []),
        "type_id": p.type_id, "geometry_ids": list(q.geometry_ids) if q and q.geometry_ids else [shape] if shape else [],
        "geometry_source_line": q.geometry_source if q else None,
        "quantity_id": q.quantity.id if q and q.quantity else None, "property_set_id": q.group_id if q else None,
        "unit_id": q.unit_id if q else None, "value": q.value if q else 1,
        "source_line": r.source, "quantity_source_line": q.quantity.source if q and q.quantity else None,
    }


def unsupported(reason, unit=None):
    return {"status":"unsupported", "answer":None, "unit":unit, "method":None, "reason":reason, "evidence":[]}


def answer(model, question: str) -> dict:
    """Answer an English takeoff question using only the selected model's native declarations."""
    prompt = question.strip().rstrip("?").strip()
    prompt = re.sub(r",? in m(?:²|2)$","",prompt,flags=re.I)
    match, single, total = COUNT.fullmatch(prompt), SINGLE.fullmatch(prompt), TOTAL.fullmatch(prompt)
    if not (match or single or total):
        return unsupported("This question does not match a supported IFC count or space-area query.")
    if match and match["model"] and key(match["model"]) not in model.names:
        return unsupported("The named model does not match the selected drawing.", "count")
    category = key(match["category"]) if match else "rooms (spaces)"
    category = {"rooms":"rooms (spaces)","spaces":"rooms (spaces)"}.get(category,category)
    if category not in CLASSES:
        return unsupported("The requested IFC occurrence class is unsupported.")
    unit = "count" if match else "m2"
    scope = match["level"] if match else single[2] if single else total[1]
    products = model.products.get(category, ())
    if scope is not None:
        levels = [eid for eid,name in model.levels.items() if key(name) == key(unquote(scope))]
        if len(levels) != 1:
            return unsupported("The storey is missing or ambiguous in this model.", unit)
        products = [p for p in products if p.storey_id == levels[0]]
    if match:
        proof = [evidence(p) for p in products]
        return {"status":"answered","answer":len(proof),"unit":unit,"method":"IFC occurrence count",
                "reason":"Distinct native occurrences in the selected model or storey.","evidence":proof}
    if single:
        products = [p for p in products if key(unquote(single[1])) in {
            key(p.room_label),key(label(p.record.fields[2])),key(label(p.record.fields[7]))}]
        if len(products) != 1:
            return unsupported("The requested room is missing or ambiguous on this storey.", unit)
    if not products or any(p.area is None for p in products):
        return unsupported("A room has no supported net-area quantity or measurable footprint in known units.", unit)
    proof = [evidence(p, area=True) for p in products]
    has_shapes = any(p.area.geometry_ids for p in products)
    has_quantities = any(p.area.quantity for p in products)
    method = "IFC room geometry and quantities" if has_shapes and has_quantities else (
        "IFC room footprint" if has_shapes else "IFC space quantity")
    return {"status":"answered","answer":math.fsum(item["value"] for item in proof),
            "unit":unit,"method":method,"reason":"Net room areas in square metres from the selected model.",
            "evidence":proof}
