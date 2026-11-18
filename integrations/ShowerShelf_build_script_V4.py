# -*- coding: utf-8 -*-
"""
ShowerShelf_3Bottle_V4 -- Phase 3 parametric build script (FreeCAD 1.0+; validated on 1.1.4)

Version 3 = the Version 1 builder (frozen) + the Phase 1B migration (V1 -> V2)
+ the Phase 1C migration (V2 -> V3).  The Phase 1C step can also convert an
open V2 document in place:

    doc = build_v3()            # fresh V3 model from scratch
    migrate_v3(doc_v2)          # or: convert an open V2 document in place

Phase 1C changes
  * reinforcing arms: the rear rim curves forward on both sides of the sleeve
    (tangent to the rim, orthogonal to the sleeve OD) and joins the sleeve with
    plan-view junction radii ArmSleeveFilletR; full-round tops, floor fillets
  * rear drain opening: rim removed down to the floor top (Z = -0.500 in)
    between the arm tangent points (DrainOpeningWidth); floor unchanged
  * sleeve top outer edge rounded (SleeveTopEdgeR) outside the arm entry zones
All geometry is native FreeCAD; edit the 'Parameters' sheet and recompute.
"""
# ======================= VERSION 1 BUILDER (frozen) =======================
"""
ShowerShelf_3Bottle_V1 -- Phase 1 parametric build script (FreeCAD 1.0+)

Builds a fully parametric, spreadsheet-driven model using only native
FreeCAD features (Spreadsheet, Part primitives, Part booleans, Part::Line,
Part::RuledSurface, Part::Revolution, App::Link, PartDesign::Fillet).
No FeaturePython / scripted features are used, so the saved FCStd recomputes
on any stock FreeCAD 1.0 install without this script.

Every dimension and placement is an expression bound to an alias in the
'Parameters' spreadsheet.  Run build(doc_name) once; afterwards edit the
spreadsheet and recompute.

Fillet strategy (robust against topological renaming): concave fillets are
added as "band minus tube" solids, convex roundings are removed with
"band minus tube" cutters.  The tube for a capsule path is two cylinders plus
two half-tori.  Only the saddle uses PartDesign::Fillet, with UseAllEdges=True,
so no edge names are referenced.
"""
import FreeCAD as App
import Part

DOC_NAME_V1 = "ShowerShelf_3Bottle_V1"
SS = "Parameters"


def P(a):
    return "%s.%s" % (SS, a)


# --------------------------------------------------------------------------
# Parameter table: (alias, expression, display unit, category, description)
# categories: MEASURED, APPROVED, CALCULATED, ASSUMED, TOOL (modelling aid)
# --------------------------------------------------------------------------
PARAMS = [
    ("# Shelf body", None, None, None, None),
    ("ShelfDepth", "=3.580 in", "in", "APPROVED", "Shelf depth, rear edge to front edge (Y)"),
    ("EndRadius", "=ShelfDepth / 2", "in", "CALCULATED", "Capsule end radius (approved 1.790 in = depth/2)"),
    ("FloorThk", "=0.150 in", "in", "APPROVED", "Floor thickness"),
    ("RimHeight", "=0.500 in", "in", "APPROVED", "Rim height above floor top"),
    ("RimThk", "=0.125 in", "in", "APPROVED", "Perimeter rim wall thickness"),
    ("RimBullnoseR", "=0.0625 in", "in", "APPROVED", "Rim top bullnose radius (<= RimThk/2)"),
    ("RimFilletR", "=0.0625 in", "in", "ASSUMED", "Rim-to-floor inside fillet radius"),
    ("FloorTopZ", "=-RimHeight", "in", "CALCULATED", "Floor top surface Z (rim top = 0)"),
    ("FloorBotZ", "=-(RimHeight + FloorThk)", "in", "CALCULATED", "Floor underside Z"),
    ("RimInnerR", "=EndRadius - RimThk", "in", "CALCULATED", "Inside radius of rim at the ends"),
    ("# Bottles", None, None, None, None),
    ("BottleDia", "=2.800 in", "in", "APPROVED", "Bottle diameter"),
    ("BottleR", "=BottleDia / 2", "in", "CALCULATED", "Bottle radius"),
    ("BottleHeight", "=8.0 in", "in", "ASSUMED", "Reference bottle height (display only)"),
    ("ClrBottleBottle", "=0.250 in", "in", "APPROVED", "Min. bottle-to-bottle clearance"),
    ("ClrBottleSleeve", "=0.125 in", "in", "APPROVED", "Min. bottle-to-sleeve clearance"),
    ("ClrBottleRim", "=0.125 in", "in", "APPROVED", "Min. end bottle-to-rim (inside) clearance"),
    ("BottleY", "=ShelfDepth / 2", "in", "ASSUMED", "Bottle centre Y (centred on shelf depth)"),
    ("BottleSleeveCC", "=BottleR + SleeveOR + ClrBottleSleeve", "in", "CALCULATED", "Bottle-to-sleeve centre distance"),
    ("BottleSleeveDX", "=sqrt(BottleSleeveCC ^ 2 - (BottleY - SleeveY) ^ 2)", "in", "CALCULATED", "X offset sleeve to adjacent bottles"),
    ("BottlePitch", "=BottleDia + ClrBottleBottle", "in", "CALCULATED", "Centre spacing of the two left bottles"),
    ("Bottle1X", "=SleeveX + BottleSleeveDX", "in", "CALCULATED", "Bottle 1 (right of sleeve) centre X"),
    ("Bottle2X", "=SleeveX - BottleSleeveDX", "in", "CALCULATED", "Bottle 2 (left, inner) centre X"),
    ("Bottle3X", "=Bottle2X - BottlePitch", "in", "CALCULATED", "Bottle 3 (left, outer / critical) centre X"),
    ("EndArcOffset", "=RimInnerR - ClrBottleRim - BottleR", "in", "CALCULATED", "End-bottle centre offset outboard of end-arc centre"),
    ("ArcCxR", "=Bottle1X - EndArcOffset", "in", "CALCULATED", "Right end-arc centre X"),
    ("ArcCxL", "=Bottle3X + EndArcOffset", "in", "CALCULATED", "Left end-arc centre X"),
    ("StraightLen", "=ArcCxR - ArcCxL", "in", "CALCULATED", "Length of straight front/rear edges"),
    ("ShelfXmin", "=ArcCxL - EndRadius", "in", "CALCULATED", "Left extreme X"),
    ("ShelfXmax", "=ArcCxR + EndRadius", "in", "CALCULATED", "Right extreme X"),
    ("ShelfLength", "=ShelfXmax - ShelfXmin", "in", "CALCULATED", "Overall shelf length"),
    ("ShelfYc", "=ShelfDepth / 2", "in", "CALCULATED", "Capsule centreline Y"),
    ("ClrBottleSide", "=RimInnerR - BottleR - abs(BottleY - ShelfYc)", "in", "CALCULATED", "Bottle to front/rear rim clearance (check)"),
    ("# Mounting sleeve", None, None, None, None),
    ("TubeOD", "=0.875 in", "in", "MEASURED", "Existing vertical tube OD"),
    ("SleeveID", "=0.895 in", "in", "APPROVED", "Sleeve inside diameter"),
    ("SleeveWall", "=0.200 in", "in", "APPROVED", "Sleeve wall thickness"),
    ("SleeveOD", "=SleeveID + 2 * SleeveWall", "in", "CALCULATED", "Sleeve OD (approved 1.295 in)"),
    ("SleeveIR", "=SleeveID / 2", "in", "CALCULATED", "Sleeve bore radius"),
    ("SleeveOR", "=SleeveOD / 2", "in", "CALCULATED", "Sleeve outer radius"),
    ("SleeveX", "=0.000 in", "in", "APPROVED", "Sleeve centre X (X origin)"),
    ("SleeveY", "=1.157 in", "in", "APPROVED", "Sleeve centre Y"),
    ("SleeveTopZ", "=0 in", "in", "APPROVED", "Sleeve top = rim top"),
    ("SleeveFilletR", "=0.100 in", "in", "ASSUMED", "Sleeve-to-floor fillet radius"),
    ("SleeveTubeClr", "=SleeveID - TubeOD", "in", "CALCULATED", "Diametral clearance on tube"),
    ("# Tapered saddle", None, None, None, None),
    ("CylDiaWall", "=1.470 in", "in", "MEASURED", "Horizontal cylinder dia at wall (nominal)"),
    ("CylDiaRear", "=1.452 in", "in", "MEASURED", "Cylinder dia at shelf rear edge, Y=0 (nominal)"),
    ("CylDiaFront", "=1.417 in", "in", "MEASURED", "Cylinder dia at saddle forward end (nominal)"),
    ("MeasUncert", "=0.010 in", "in", "MEASURED", "Diameter measurement uncertainty (+/-)"),
    ("SaddleY0", "=0.000 in", "in", "APPROVED", "Saddle start Y"),
    ("SaddleLength", "=1.875 in", "in", "APPROVED", "Saddle length along Y"),
    ("SaddleY1", "=SaddleY0 + SaddleLength", "in", "CALCULATED", "Saddle forward end Y"),
    ("SaddleWall", "=0.200 in", "in", "APPROVED", "Saddle wall thickness"),
    ("SaddleWrap", "=200", "deg", "APPROVED", "Saddle wrap angle (design target, not validated)"),
    ("CrownZ", "=-0.600 in", "in", "APPROVED", "Saddle inner crown Z at Y=SaddleY0"),
    ("SaddleClr", "=0.010 in", "in", "APPROVED", "Saddle radial clearance (provisional)"),
    ("SaddleEdgeR", "=0.040 in", "in", "ASSUMED", "Saddle edge fillet radius (all saddle edges)"),
    ("TaperSlope", "=(CylDiaRear - CylDiaFront) / SaddleLength", "in/in", "CALCULATED", "Diametral taper (driving value; overwrite to override)"),
    ("DesignDiaRear", "=CylDiaRear", "in", "CALCULATED", "Design cylinder dia at SaddleY0"),
    ("DesignDiaFront", "=DesignDiaRear - TaperSlope * SaddleLength", "in", "CALCULATED", "Design cylinder dia at SaddleY1"),
    ("WallDistImplied", "=(CylDiaWall - CylDiaRear) / TaperSlope", "in", "CALCULATED", "Implied wall-to-rear-edge distance (linear taper)"),
    ("SaddleRi0", "=DesignDiaRear / 2 + SaddleClr", "in", "CALCULATED", "Saddle inner radius at Y0"),
    ("SaddleRi1", "=DesignDiaFront / 2 + SaddleClr", "in", "CALCULATED", "Saddle inner radius at Y1"),
    ("SaddleRo0", "=SaddleRi0 + SaddleWall", "in", "CALCULATED", "Saddle outer radius at Y0"),
    ("SaddleRo1", "=SaddleRi1 + SaddleWall", "in", "CALCULATED", "Saddle outer radius at Y1"),
    ("SaddleAxisX", "=SleeveX", "in", "ASSUMED", "Cylinder axis X (assumed under sleeve)"),
    ("SaddleAxisZ", "=CrownZ - SaddleRi0", "in", "CALCULATED", "Cylinder axis Z (axis assumed horizontal)"),
    ("SaddleLipAngle", "=(SaddleWrap - 180) / 2", "deg", "CALCULATED", "Lip extension below the axis, each side"),
    ("SnapOpen0", "=2 * SaddleRi0 * cos(SaddleLipAngle)", "in", "CALCULATED", "Opening width at Y0 (sharp-corner)"),
    ("SnapOpen1", "=2 * SaddleRi1 * cos(SaddleLipAngle)", "in", "CALCULATED", "Opening width at Y1 (sharp-corner)"),
    ("SnapInterf0", "=DesignDiaRear - SnapOpen0", "in", "CALCULATED", "Diametral snap interference at Y0 (sharp-corner)"),
    ("SnapInterf1", "=DesignDiaFront - SnapOpen1", "in", "CALCULATED", "Diametral snap interference at Y1 (sharp-corner)"),
    ("# Drainage slots", None, None, None, None),
    ("SlotLength", "=1.750 in", "in", "ASSUMED", "Slot overall length (along Y)"),
    ("SlotWidth", "=0.250 in", "in", "ASSUMED", "Slot width"),
    ("SlotFilletR", "=0.040 in", "in", "APPROVED", "Slot top & bottom edge fillet radius"),
    ("SlotY", "=BottleY", "in", "ASSUMED", "Slot centre Y"),
    ("Slot1X", "=Bottle1X", "in", "ASSUMED", "Slot 1 centre X (under bottle 1)"),
    ("Slot2X", "=Bottle2X", "in", "ASSUMED", "Slot 2 centre X (under bottle 2)"),
    ("Slot3X", "=Bottle3X", "in", "ASSUMED", "Slot 3 centre X (under bottle 3)"),
    ("SlotHalfW", "=SlotWidth / 2", "in", "CALCULATED", "Slot half width"),
    ("SlotHalfC", "=(SlotLength - SlotWidth) / 2", "in", "CALCULATED", "Slot end-centre half spacing"),
    ("# Modelling tolerances (not design dimensions)", None, None, None, None),
    ("Eps", "=0.010 in", "in", "TOOL", "Boolean tool overlap"),
    ("Big", "=0.200 in", "in", "TOOL", "Trim-tool margin"),
]


def make_sheet(doc):
    s = doc.addObject("Spreadsheet::Sheet", SS)
    s.Label = SS
    hdr = ["Alias / item", "Value", "Unit shown", "Category", "Description"]
    for c, h in zip("ABCDE", hdr):
        s.set("%s1" % c, h)
    r = 2
    for alias, expr, unit, cat, desc in PARAMS:
        if expr is None:
            s.set("A%d" % r, alias.lstrip("# ").upper())
            r += 1
            continue
        s.set("A%d" % r, alias)
        s.set("B%d" % r, expr)
        s.setAlias("B%d" % r, alias)
        if unit in ("in",):
            s.setDisplayUnit("B%d" % r, "in")
        s.set("C%d" % r, unit or "")
        s.set("D%d" % r, cat)
        s.set("E%d" % r, desc)
        r += 1
    # Second pass: re-enter every formula so that references to aliases defined
    # on later rows register as dependencies (FreeCAD does not bind forward
    # references made before the alias exists).
    for rr in range(2, r):
        if s.getAlias("B%d" % rr):
            s.set("B%d" % rr, s.getContents("B%d" % rr))
    s.setColumnWidth("A", 140)
    s.setColumnWidth("B", 110)
    s.setColumnWidth("E", 380)
    return s


class B:
    """Small builder for expression-driven native features."""

    def __init__(self, doc):
        self.doc = doc
        self.intermediate = []

    def _add(self, typ, name, group=None):
        o = self.doc.addObject(typ, name)
        if group is not None:
            group.addObject(o)
        self.intermediate.append(o)
        return o

    def _place(self, o, x, y, z):
        o.setExpression(".Placement.Base.x", x)
        o.setExpression(".Placement.Base.y", y)
        o.setExpression(".Placement.Base.z", z)

    # primitives -----------------------------------------------------------
    def box(self, n, L, W, H, x, y, z, g):
        o = self._add("Part::Box", n, g)
        o.setExpression("Length", L)
        o.setExpression("Width", W)
        o.setExpression("Height", H)
        self._place(o, x, y, z)
        return o

    def cyl(self, n, r, h, x, y, z, g, axis="Z"):
        o = self._add("Part::Cylinder", n, g)
        o.setExpression("Radius", r)
        o.setExpression("Height", h)
        if axis == "X":
            o.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90)
        elif axis == "Y":
            # extra 90 deg spin about own axis keeps the cylinder seam off the
            # torus seam (coincident seams inflate tolerances in the fuse)
            o.Placement.Rotation = App.Rotation(App.Vector(1, 0, 0), -90).multiply(
                App.Rotation(App.Vector(0, 0, 1), 90))
        self._place(o, x, y, z)
        return o

    def torus(self, n, R1, R2, x, y, z, rotz, ang3, g):
        o = self._add("Part::Torus", n, g)
        o.setExpression("Radius1", R1)
        o.setExpression("Radius2", R2)
        o.Angle3 = ang3
        o.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), rotz)
        self._place(o, x, y, z)
        return o

    def fuse(self, n, objs, g, refine=False):
        o = self._add("Part::MultiFuse", n, g)
        o.Shapes = objs
        o.Refine = refine
        return o

    def cut(self, n, base, tool, g, refine=False):
        o = self._add("Part::Cut", n, g)
        o.Base = base
        o.Tool = tool
        o.Refine = refine
        return o

    def common(self, n, objs, g):
        o = self._add("Part::MultiCommon", n, g)
        o.Shapes = objs
        return o

    # composite shapes -----------------------------------------------------
    def capsuleX(self, n, hw, z0, h, g):
        """Capsule on the shelf centreline, half-width hw (=end radius)."""
        bx = self.box(n + "_Box", P("StraightLen"), "2 * (%s)" % hw, h,
                      P("ArcCxL"), "%s - (%s)" % (P("ShelfYc"), hw), z0, g)
        cl = self.cyl(n + "_EndL", hw, h, P("ArcCxL"), P("ShelfYc"), z0, g)
        cr = self.cyl(n + "_EndR", hw, h, P("ArcCxR"), P("ShelfYc"), z0, g)
        return self.fuse(n, [bx, cl, cr], g, refine=True)

    def tubeX(self, n, a, r, z, g):
        """Tube of radius r swept around the shelf capsule path of half-width a."""
        c1 = self.cyl(n + "_Rear", r, P("StraightLen"), P("ArcCxL"),
                      "%s - (%s)" % (P("ShelfYc"), a), z, g, axis="X")
        c2 = self.cyl(n + "_Front", r, P("StraightLen"), P("ArcCxL"),
                      "%s + (%s)" % (P("ShelfYc"), a), z, g, axis="X")
        tr = self.torus(n + "_EndR", a, r, P("ArcCxR"), P("ShelfYc"), z, -90, 180, g)
        tl = self.torus(n + "_EndL", a, r, P("ArcCxL"), P("ShelfYc"), z, 90, 180, g)
        return self.fuse(n, [c1, c2, tr, tl], g)

    def ringX(self, n, a_out, a_in, z0, h, g):
        """Band between two concentric capsules (inner one taller for clean cut)."""
        o = self.capsuleX(n + "_Out", a_out, z0, h, g)
        i = self.capsuleX(n + "_In", a_in, "%s - %s" % (z0, P("Eps")),
                          "%s + 2 * %s" % (h, P("Eps")), g)
        return self.cut(n, o, i, g)

    def slotY(self, n, hw, z0, h, g):
        """Slot capsule along Y at X=0, Y=SlotY (positioned later by links)."""
        y1 = "%s - %s" % (P("SlotY"), P("SlotHalfC"))
        bx = self.box(n + "_Box", "2 * (%s)" % hw, "2 * %s" % P("SlotHalfC"), h,
                      "-(%s)" % hw, y1, z0, g)
        c1 = self.cyl(n + "_End1", hw, h, "0 mm", y1, z0, g)
        c2 = self.cyl(n + "_End2", hw, h, "0 mm",
                      "%s + %s" % (P("SlotY"), P("SlotHalfC")), z0, g)
        return self.fuse(n, [bx, c1, c2], g, refine=True)

    def tubeY(self, n, a, r, z, g):
        y1 = "%s - %s" % (P("SlotY"), P("SlotHalfC"))
        y2 = "%s + %s" % (P("SlotY"), P("SlotHalfC"))
        L = "2 * %s" % P("SlotHalfC")
        c1 = self.cyl(n + "_L", r, L, "-(%s)" % a, y1, z, g, axis="Y")
        c2 = self.cyl(n + "_R", r, L, "%s" % a, y1, z, g, axis="Y")
        t2 = self.torus(n + "_End2", a, r, "0 mm", y2, z, 0, 180, g)
        t1 = self.torus(n + "_End1", a, r, "0 mm", y1, z, 180, 180, g)
        return self.fuse(n, [c1, c2, t1, t2], g)

    def ringY(self, n, a_out, a_in, z0, h, g):
        o = self.slotY(n + "_Out", a_out, z0, h, g)
        i = self.slotY(n + "_In", a_in, "%s - %s" % (z0, P("Eps")),
                       "%s + 2 * %s" % (h, P("Eps")), g)
        return self.cut(n, o, i, g)


def build(doc_name=DOC_NAME_V1):
    if doc_name in App.listDocuments():
        raise RuntimeError("Document %s already open - refusing to modify it" % doc_name)
    doc = App.newDocument(doc_name)
    grp = {}
    for key, label in [("par", "01_Parameters"), ("floor", "02_ShelfFloor"),
                       ("rim", "03_PerimeterRim"), ("sleeve", "04_MountingSleeve"),
                       ("saddle", "05_TaperedSaddle"), ("slots", "06_DrainageSlots"),
                       ("fil", "07_Fillets"), ("bot", "08_BottleReference"),
                       ("fin", "09_FinalManufacturingSolid")]:
        grp[key] = doc.addObject("App::DocumentObjectGroup", label)
    sheet = make_sheet(doc)
    grp["par"].addObject(sheet)
    doc.recompute()
    b = B(doc)

    # --- 02 floor -----------------------------------------------------------
    floor = b.capsuleX("ShelfFloor", P("EndRadius"), P("FloorBotZ"), P("FloorThk"), grp["floor"])

    # --- 03 rim (band from floor top to rim top), overlaps floor by Eps ----
    rim = b.ringX("PerimeterRim", P("EndRadius"), P("RimInnerR"),
                  "%s - %s" % (P("FloorTopZ"), P("Eps")),
                  "%s + %s" % (P("RimHeight"), P("Eps")), grp["rim"])

    # --- 07a rim-to-floor concave fillet (additive) -------------------------
    g = grp["fil"]
    rfband = b.ringX("RimFloorFillet_Band", P("RimInnerR"),
                     "%s - %s" % (P("RimInnerR"), P("RimFilletR")),
                     P("FloorTopZ"), P("RimFilletR"), g)
    rftube = b.tubeX("RimFloorFillet_Tube", "%s - %s" % (P("RimInnerR"), P("RimFilletR")),
                     P("RimFilletR"), "%s + %s" % (P("FloorTopZ"), P("RimFilletR")), g)
    rimfillet = b.cut("RimFloorFillet", rfband, rftube, g)

    # --- 07b rim bullnose cutters (subtractive) ------------------------------
    bnz0 = "-%s" % P("RimBullnoseR")
    bnh = "%s + %s" % (P("RimBullnoseR"), P("Eps"))
    bo_band = b.ringX("BullnoseOuter_Band", "%s + %s" % (P("EndRadius"), P("Eps")),
                      "%s - %s" % (P("EndRadius"), P("RimBullnoseR")), bnz0, bnh, g)
    bo_tube = b.tubeX("BullnoseOuter_Tube", "%s - %s" % (P("EndRadius"), P("RimBullnoseR")),
                      P("RimBullnoseR"), bnz0, g)
    bull_out = b.cut("BullnoseOuter_Cutter", bo_band, bo_tube, g)
    bi_band = b.ringX("BullnoseInner_Band", "%s + %s" % (P("RimInnerR"), P("RimBullnoseR")),
                      "%s - %s" % (P("RimInnerR"), P("Eps")), bnz0, bnh, g)
    bi_tube = b.tubeX("BullnoseInner_Tube", "%s + %s" % (P("RimInnerR"), P("RimBullnoseR")),
                      P("RimBullnoseR"), bnz0, g)
    bull_in = b.cut("BullnoseInner_Cutter", bi_band, bi_tube, g)

    # --- 04 sleeve -----------------------------------------------------------
    gs = grp["sleeve"]
    sleeve = b.cyl("Sleeve_Outer", P("SleeveOR"), "%s - %s" % (P("SleeveTopZ"), P("SaddleAxisZ")),
                   P("SleeveX"), P("SleeveY"), P("SaddleAxisZ"), gs)
    bore = b.cyl("Sleeve_Bore", P("SleeveIR"),
                 "%s - %s + 2 * %s" % (P("SleeveTopZ"), P("SaddleAxisZ"), P("Eps")),
                 P("SleeveX"), P("SleeveY"), "%s - %s" % (P("SaddleAxisZ"), P("Eps")), gs)
    # sleeve-to-floor fillet ring (additive)
    # ring sits exactly on the floor top and against the sleeve OD (shared faces,
    # no tangent overlaps) so booleans and STEP round-trips stay clean
    sf_o = b.cyl("SleeveFillet_RingOut", "%s + %s" % (P("SleeveOR"), P("SleeveFilletR")),
                 P("SleeveFilletR"), P("SleeveX"), P("SleeveY"), P("FloorTopZ"), g)
    sf_i = b.cyl("SleeveFillet_RingIn", P("SleeveOR"),
                 "%s + 2 * %s" % (P("SleeveFilletR"), P("Eps")),
                 P("SleeveX"), P("SleeveY"), "%s - %s" % (P("FloorTopZ"), P("Eps")), g)
    sf_ring = b.cut("SleeveFillet_Ring", sf_o, sf_i, g)
    sf_tor = b.torus("SleeveFillet_Torus", "%s + %s" % (P("SleeveOR"), P("SleeveFilletR")),
                     P("SleeveFilletR"), P("SleeveX"), P("SleeveY"),
                     "%s + %s" % (P("FloorTopZ"), P("SleeveFilletR")), 0, 360, g)
    sleevefillet = b.cut("SleeveFloorFillet", sf_ring, sf_tor, g)

    # --- 05 tapered saddle -----------------------------------------------------
    ga = grp["saddle"]
    # outer cone sector: Angle = wrap, rotated so the sector is centred on +Z
    ocone = b._add("Part::Cone", "Saddle_OuterConeSector", ga)
    ocone.setExpression("Radius1", P("SaddleRo1"))
    ocone.setExpression("Radius2", P("SaddleRo0"))
    ocone.setExpression("Height", P("SaddleLength"))
    ocone.setExpression("Angle", P("SaddleWrap"))
    ocone.setExpression(".Placement.Rotation",
                        "rotation(vector(0; 1; 0); %s) * rotation(vector(1; 0; 0); 90)" % P("SaddleLipAngle"))
    b._place(ocone, P("SaddleAxisX"), P("SaddleY1"), P("SaddleAxisZ"))
    # inner (cylinder + clearance) cone, extended by Big at both ends on the same taper
    icone = b._add("Part::Cone", "Saddle_InnerConeTool", ga)
    icone.setExpression("Radius1", "%s - %s * %s / 2" % (P("SaddleRi1"), P("TaperSlope"), P("Big")))
    icone.setExpression("Radius2", "%s + %s * %s / 2" % (P("SaddleRi0"), P("TaperSlope"), P("Big")))
    icone.setExpression("Height", "%s + 2 * %s" % (P("SaddleLength"), P("Big")))
    icone.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90).multiply(App.Rotation(App.Vector(1, 0, 0), 90))
    b._place(icone, P("SaddleAxisX"), "%s + %s" % (P("SaddleY1"), P("Big")), P("SaddleAxisZ"))
    rev = b.cut("Saddle_Shell", ocone, icone, ga)
    body = doc.addObject("PartDesign::Body", "Saddle_FilletBody")
    ga.addObject(body)
    body.BaseFeature = rev
    doc.recompute()
    basefeat = [o for o in body.Group if o.TypeId == "PartDesign::FeatureBase"][0]
    sfil = body.newObject("PartDesign::Fillet", "Saddle_EdgeFillet")
    sfil.Base = (basefeat, ["Edge1"])
    sfil.UseAllEdges = True
    sfil.setExpression("Radius", P("SaddleEdgeR"))
    b.intermediate += [body, basefeat, sfil]
    # trim saddle top just below the floor top (inside the floor, so no material
    # change; avoids a face coplanar with the floor top that splits edges)
    trim = b.box("Saddle_TrimBox", "2 * %s + 2 * %s" % (P("SaddleRo0"), P("Big")),
                 "%s + 2 * %s" % (P("SaddleLength"), P("Big")),
                 "%s - %s - (%s - %s - %s)" % (P("FloorTopZ"), P("Eps"), P("SaddleAxisZ"), P("SaddleRo0"), P("Big")),
                 "%s - %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), P("Big")),
                 "%s - %s" % (P("SaddleY0"), P("Big")),
                 "%s - %s - %s" % (P("SaddleAxisZ"), P("SaddleRo0"), P("Big")), ga)
    saddle = b.common("Saddle_Trimmed", [body, trim], ga)
    # cylinder envelope cut from floor/sleeve: revolve inner line 360 deg (same surface as saddle)
    cav = b._add("Part::Cone", "Saddle_CylinderEnvelope", ga)
    cav.setExpression("Radius1", P("SaddleRi1"))
    cav.setExpression("Radius2", P("SaddleRi0"))
    cav.setExpression("Height", P("SaddleLength"))
    cav.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90).multiply(App.Rotation(App.Vector(1, 0, 0), 90))
    b._place(cav, P("SaddleAxisX"), P("SaddleY1"), P("SaddleAxisZ"))

    # --- 06 drainage slots: one master cutter at X=0, placed by App::Link ----
    gd = grp["slots"]
    thru = b.slotY("Slot_Through", P("SlotHalfW"), "%s - %s" % (P("FloorBotZ"), P("Eps")),
                   "%s + 2 * %s" % (P("FloorThk"), P("Eps")), gd)
    top_band = b.ringY("SlotTopEdge_Band", "%s + %s" % (P("SlotHalfW"), P("SlotFilletR")),
                       "%s - %s" % (P("SlotHalfW"), P("Eps")),
                       "%s - %s" % (P("FloorTopZ"), P("SlotFilletR")),
                       "%s + %s" % (P("SlotFilletR"), P("Eps")), gd)
    top_tube = b.tubeY("SlotTopEdge_Tube", "%s + %s" % (P("SlotHalfW"), P("SlotFilletR")),
                       P("SlotFilletR"), "%s - %s" % (P("FloorTopZ"), P("SlotFilletR")), gd)
    top_cut = b.cut("SlotTopEdge_Cutter", top_band, top_tube, gd)
    bot_band = b.ringY("SlotBotEdge_Band", "%s + %s" % (P("SlotHalfW"), P("SlotFilletR")),
                       "%s - %s" % (P("SlotHalfW"), P("Eps")),
                       "%s - %s" % (P("FloorBotZ"), P("Eps")),
                       "%s + %s" % (P("SlotFilletR"), P("Eps")), gd)
    bot_tube = b.tubeY("SlotBotEdge_Tube", "%s + %s" % (P("SlotHalfW"), P("SlotFilletR")),
                       P("SlotFilletR"), "%s + %s" % (P("FloorBotZ"), P("SlotFilletR")), gd)
    bot_cut = b.cut("SlotBotEdge_Cutter", bot_band, bot_tube, gd)
    slot_sets = {}
    for key, master in (("Thru", thru), ("TopEdge", top_cut), ("BotEdge", bot_cut)):
        lks = []
        for i in (1, 2, 3):
            lk = b._add("App::Link", "DrainSlot%d_%s" % (i, key), gd)
            lk.LinkedObject = master
            lk.setExpression(".Placement.Base.x", P("Slot%dX" % i))
            lks.append(lk)
        slot_sets[key] = b.fuse("DrainSlots_%s" % key, lks, gd)

    # --- 09 final boolean chain (sequential cuts: robust with tangent fillet tools)
    gf = grp["fin"]
    adds = b.fuse("Fin_01_AddFloorRimSleeve", [floor, rim, rimfillet, sleeve, sleevefillet], gf, refine=True)
    env_cut = b.cut("Fin_02_CutCylinderEnvelope", adds, cav, gf)
    cur = b.fuse("Fin_03_AddSaddle", [env_cut, saddle], gf)
    for i, (nm, tool) in enumerate([("CutSleeveBore", bore), ("CutBullnoseOuter", bull_out),
                                    ("CutBullnoseInner", bull_in), ("CutSlotsThrough", slot_sets["Thru"]),
                                    ("CutSlotTopEdges", slot_sets["TopEdge"]),
                                    ("CutSlotBottomEdges", slot_sets["BotEdge"])]):
        cur = b.cut("Fin_%02d_%s" % (i + 4, nm), cur, tool, gf)
    final = doc.addObject("Part::Refine", "ShelfSolid")
    final.Label = "ShelfSolid_Manufacturing"
    final.Source = cur
    gf.addObject(final)

    # --- 08 bottle reference geometry -----------------------------------------
    bottles = []
    for i in (1, 2, 3):
        bo = doc.addObject("Part::Cylinder", "RefBottle%d" % i)
        grp["bot"].addObject(bo)
        bo.setExpression("Radius", P("BottleR"))
        bo.setExpression("Height", P("BottleHeight"))
        bo.setExpression(".Placement.Base.x", P("Bottle%dX" % i))
        bo.setExpression(".Placement.Base.y", P("BottleY"))
        bo.setExpression(".Placement.Base.z", P("FloorTopZ"))
        bottles.append(bo)

    notes = doc.addObject("App::TextDocument", "ModelNotes")
    grp["par"].addObject(notes)
    notes.Text = NOTES

    doc.recompute()
    for o in b.intermediate:
        try:
            o.Visibility = False
        except Exception:
            pass
    if App.GuiUp:
        import FreeCADGui as Gui
        final.ViewObject.ShapeColor = (0.85, 0.85, 0.80)
        for bo in bottles:
            bo.ViewObject.Transparency = 75
            bo.ViewObject.ShapeColor = (0.3, 0.5, 0.9)
        for o in b.intermediate:
            try:
                o.ViewObject.Visibility = False
            except Exception:
                pass
        final.ViewObject.Visibility = True
        for bo in bottles:
            bo.ViewObject.Visibility = True
        try:
            Gui.ActiveDocument.ActiveView.viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
    return doc


NOTES = """ShowerShelf_3Bottle_V1 - Phase 1 model notes
Units: model in mm; Parameters sheet entered/displayed in inches.
Coordinates: X along length (sleeve centreline X=0, +X = 1-bottle side),
Y from rear edge (Y=0) toward front, Z up (Z=0 = rim top).

All geometry is native FreeCAD (no scripted features). Edit only the
Parameters spreadsheet, then Recompute.

Feature map:
 02_ShelfFloor      capsule slab FloorBotZ..FloorTopZ
 03_PerimeterRim    capsule band EndRadius..RimInnerR up to Z=0
 04_MountingSleeve  outer cylinder (to saddle axis) and through bore
 05_TaperedSaddle   outer cone sector (Angle=SaddleWrap, centred on +Z by a
                    rotation expression) minus inner cone (cylinder +
                    clearance, extended on the same taper) -> PartDesign
                    Fillet (UseAllEdges, Radius=SaddleEdgeR) -> trimmed flush
                    with floor top.  Saddle_CylinderEnvelope (inner cone,
                    Y0..Y1) is cut from floor and sleeve.
 06_DrainageSlots   master through-cutter + top/bottom edge-rounding
                    cutters, each placed 3x with App::Link (X = Slot#X)
 07_Fillets         band-minus-tube solids: rim-floor fillet (added),
                    sleeve-floor fillet (added), rim bullnose (cut)
 08_BottleReference reference cylinders - NOT part of ShelfSolid
 09_Final...        boolean chain -> Part::Refine 'ShelfSolid' (export this)

Constraints the parameters must respect:
 0 < RimBullnoseR <= RimThk/2;  SlotFilletR < FloorThk/2;
 SlotFilletR < SlotWidth/2;  CrownZ above FloorBotZ thins the floor locally.
 TaperSlope is calculated from the measured diameters; overwrite cell to
 set it independently.  Saddle crown is set at Y = SaddleY0 with a
 horizontal axis (assumption).
"""



# ======================= PHASE 1B MIGRATION (V1 -> V2) ======================
import math

class Bld:
    def __init__(self, doc):
        self.doc = doc
        self.new = []

    def add(self, typ, name, group=None):
        o = self.doc.addObject(typ, name)
        if group is not None:
            group.addObject(o)
        self.new.append(o)
        return o

    def place(self, o, x, y, z):
        o.setExpression(".Placement.Base.x", x)
        o.setExpression(".Placement.Base.y", y)
        o.setExpression(".Placement.Base.z", z)

    def box(self, n, L, W, H, x, y, z, g):
        o = self.add("Part::Box", n, g)
        o.setExpression("Length", L); o.setExpression("Width", W); o.setExpression("Height", H)
        self.place(o, x, y, z)
        return o

    def cyl(self, n, r, h, x, y, z, g, axis="Z"):
        o = self.add("Part::Cylinder", n, g)
        o.setExpression("Radius", r); o.setExpression("Height", h)
        if axis == "X":
            o.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90)
        self.place(o, x, y, z)
        return o

    def torus(self, n, R1, R2, x, y, z, rotz, ang3, g):
        o = self.add("Part::Torus", n, g)
        o.setExpression("Radius1", R1); o.setExpression("Radius2", R2)
        o.Angle3 = ang3
        o.Placement.Rotation = App.Rotation(App.Vector(0, 0, 1), rotz)
        self.place(o, x, y, z)
        return o

    def fuse(self, n, objs, g, refine=False):
        o = self.add("Part::MultiFuse", n, g)
        o.Shapes = objs; o.Refine = refine
        return o

    def cut(self, n, base, tool, g, refine=False):
        o = self.add("Part::Cut", n, g)
        o.Base = base; o.Tool = tool; o.Refine = refine
        return o

    # slot capsule along X centred on (0, DrainSlotY)
    def slotX(self, n, hw, z0, h, g):
        hc = P("DrainSlotHalfC")
        bx = self.box(n + "_Box", "2 * %s" % hc, "2 * (%s)" % hw, h,
                      "-%s" % hc, "%s - (%s)" % (P("DrainSlotY"), hw), z0, g)
        c1 = self.cyl(n + "_EndL", hw, h, "-%s" % hc, P("DrainSlotY"), z0, g)
        c2 = self.cyl(n + "_EndR", hw, h, hc, P("DrainSlotY"), z0, g)
        return self.fuse(n, [bx, c1, c2], g, refine=True)

    def tubeX(self, n, a, r, z, g):
        hc = P("DrainSlotHalfC")
        L = "2 * %s" % hc
        c1 = self.cyl(n + "_Rear", r, L, "-%s" % hc, "%s - (%s)" % (P("DrainSlotY"), a), z, g, axis="X")
        c2 = self.cyl(n + "_Front", r, L, "-%s" % hc, "%s + (%s)" % (P("DrainSlotY"), a), z, g, axis="X")
        tr = self.torus(n + "_EndR", a, r, hc, P("DrainSlotY"), z, -90, 180, g)
        tl = self.torus(n + "_EndL", a, r, "-%s" % hc, P("DrainSlotY"), z, 90, 180, g)
        return self.fuse(n, [c1, c2, tr, tl], g)

    def ringX(self, n, a_out, a_in, z0, h, g):
        o = self.slotX(n + "_Out", a_out, z0, h, g)
        i = self.slotX(n + "_In", a_in, "%s - %s" % (z0, P("Eps")), "%s + 2 * %s" % (h, P("Eps")), g)
        return self.cut(n, o, i, g)


def _row_of(s, alias):
    return int(s.getCellFromAlias(alias)[1:])


def _set_row(s, r, alias, expr, unit, cat, desc):
    old = s.getAlias("B%d" % r)
    if old and old != alias:
        s.setAlias("B%d" % r, "")
    s.set("A%d" % r, alias)
    s.set("B%d" % r, expr)
    if alias:
        s.setAlias("B%d" % r, alias)
    if unit == "in":
        s.setDisplayUnit("B%d" % r, "in")
    s.set("C%d" % r, unit)
    s.set("D%d" % r, cat)
    s.set("E%d" % r, desc)


def _sharp(shape, e, tol=10.0):
    fs = shape.ancestorsOfType(e, Part.Face)
    if len(fs) != 2:
        return False
    p = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    n = []
    for f in fs:
        u, v = f.Surface.parameter(p)
        n.append(f.normalAt(u, v))
    a = math.degrees(n[0].getAngle(n[1]))
    return a > tol


def _edge_names(shape, pred):
    return ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if pred(e)]


def _group(doc, suffix):
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label.endswith(suffix):
            return o
    raise RuntimeError("group %s not found" % suffix)


# ------------------------------------------------------------------ migrate
def migrate(doc):
    s = doc.getObject(SS)
    b = Bld(doc)
    log = []

    # ---- 1. remove the three V1 drainage slots ------------------------------
    gslots = _group(doc, "_DrainageSlots")
    fin7, fin8, fin9 = doc.Fin_07_CutSlotsThrough, doc.Fin_08_CutSlotTopEdges, doc.Fin_09_CutSlotBottomEdges
    old_slot_objs = list(gslots.Group)
    # temporarily point the cuts at a harmless tool so the old objects can go
    for f in (fin7, fin8, fin9):
        f.Tool = None
    names = [o.Name for o in old_slot_objs]
    # delete dependants first (reverse creation order)
    for n in reversed(names):
        if doc.getObject(n):
            doc.removeObject(n)
    log.append("removed %d V1 slot objects" % len(names))

    # ---- 2. parameters ------------------------------------------------------
    rc = _row_of(s, "CrownZ")
    s.setAlias("B%d" % rc, "")
    _set_row(s, rc, "SaddleCrownZ", "=-0.650 in", "in", "APPROVED",
             "Saddle inner crown Z at Y=SaddleY0 (Phase 1B: = floor underside)")
    ra = _row_of(s, "SaddleAxisZ")
    s.set("B%d" % ra, "=SaddleCrownZ - SaddleRi0")
    # new SaddleFloorFilletR row after SaddleEdgeR
    re_ = _row_of(s, "SaddleEdgeR")
    s.insertRows(str(re_ + 1), 1)
    _set_row(s, re_ + 1, "SaddleFloorFilletR", "=0.200 in", "in", "APPROVED",
             "Saddle-to-floor-underside reinforcing fillet radius")
    s.set("D%d" % re_, "ASSUMED")
    s.set("E%d" % re_, "Saddle lip & inner-end edge fillet radius")
    # floor-over-crown check value (after SaddleAxisZ)
    ra = _row_of(s, "SaddleAxisZ")
    s.insertRows(str(ra + 1), 1)
    _set_row(s, ra + 1, "FloorOverCrown", "=FloorTopZ - SaddleCrownZ", "in", "CALCULATED",
             "Floor material above saddle crown (must be >= FloorThk)")
    s.insertRows(str(ra + 2), 2)
    _set_row(s, ra + 2, "SaddleModelMarginLo", "=(FloorTopZ + FloorBotZ) / 2 - SaddleCrownZ", "in", "CALCULATED",
             "(model check) must be > 0: inner crown below mid-floor")
    _set_row(s, ra + 3, "SaddleModelMarginHi", "=SaddleCrownZ + SaddleWall - (FloorTopZ + FloorBotZ) / 2", "in", "CALCULATED",
             "(model check) must be > 0: outer crown above mid-floor")
    # slot rows: replace in place (V1 had 9 rows SlotLength..SlotHalfC)
    r0 = _row_of(s, "SlotLength")
    for a in ("SlotLength", "SlotWidth", "SlotFilletR", "SlotY", "Slot1X", "Slot2X", "Slot3X", "SlotHalfW", "SlotHalfC"):
        s.setAlias(s.getCellFromAlias(a), "")
    s.insertRows(str(r0 + 9), 2)
    rows = [
        ("DrainSlotCount", "=2", "", "APPROVED", "Number of drainage slots (first at LeftX, last at RightX; >= 2)"),
        ("DrainSlotLength", "=1.000 in", "in", "APPROVED", "Slot overall length (along X)"),
        ("DrainSlotWidth", "=0.250 in", "in", "APPROVED", "Slot width (along Y)"),
        ("DrainSlotFilletR", "=0.040 in", "in", "APPROVED", "Slot top & bottom edge fillet radius"),
        ("DrainSlotLeftX", "=Bottle3X", "in", "CALCULATED", "Left slot centre X = leftmost bottle centre"),
        ("DrainSlotRightX", "=Bottle1X", "in", "CALCULATED", "Right slot centre X = rightmost bottle centre"),
        ("DrainSlotY", "=BottleY", "in", "CALCULATED", "Slot centre Y = bottle centre Y"),
        ("DrainSlotPitch", "=(DrainSlotRightX - DrainSlotLeftX) / (DrainSlotCount - 1)", "in", "CALCULATED", "Slot-to-slot spacing along X"),
        ("DrainSlotHalfW", "=DrainSlotWidth / 2", "in", "CALCULATED", "Slot half width"),
        ("DrainSlotHalfC", "=(DrainSlotLength - DrainSlotWidth) / 2", "in", "CALCULATED", "Slot end-centre half spacing"),
        ("DrainSlotMinCount", "=DrainSlotCount", "", "CALCULATED", "(check) slot count echo"),
    ]
    rows = rows[:-1]
    for k, row in enumerate(rows):
        _set_row(s, r0 + k, *row)
    for k in range(len(rows), 11):
        for c in "ABCDE":
            s.set("%s%d" % (c, r0 + k), "")
    # second pass: re-enter formulas so forward references bind
    r = 2
    while r < 200:
        if s.getAlias("B%d" % r):
            s.set("B%d" % r, s.getContents("B%d" % r))
        r += 1
    doc.recompute()
    log.append("parameters updated")

    # ---- 3. saddle: PartDesign upper body (floor patch + junction fillet) + lower body (lips)
    ga = _group(doc, "_TaperedSaddle")
    # The V1 saddle (Part cone sector -> Part booleans -> PartDesign fillet) cannot
    # carry the new junction fillet: Part boolean features apply automatic fuzzy
    # tolerances (~1e-4 mm) and PartDesign fillets on such bases come out invalid.
    # V2 builds the saddle and a local floor patch entirely from PartDesign
    # primitives in one body, then fillets inside that body.
    old = ["Saddle_FilletBody", "Saddle_Trimmed", "Saddle_TrimBox", "Saddle_Shell",
           "Saddle_InnerConeTool", "Saddle_OuterConeSector"]
    doc.Fin_03_AddSaddle.Shapes = [doc.Fin_02_CutCylinderEnvelope]
    oldbody = doc.getObject("Saddle_FilletBody")
    if oldbody:
        for o in list(oldbody.Group):
            oldbody.removeObject(o)
            doc.removeObject(o.Name)
    for n in old:
        if doc.getObject(n):
            doc.removeObject(n)
    def mkbody(name):
        bd = doc.addObject("PartDesign::Body", name)
        ga.addObject(bd)
        b.new.append(bd)
        return bd

    def prim(bd, typ, name):
        o = bd.newObject(typ, name)
        try:
            o.MapMode = "Deactivated"
        except Exception:
            pass
        o.Refine = False
        b.new.append(o)
        return o

    R = P("SaddleFloorFilletR")
    rot_y = App.Rotation(App.Vector(0, 1, 0), 90).multiply(App.Rotation(App.Vector(1, 0, 0), 90))

    def outer_cone(bd, name):
        oc = prim(bd, "PartDesign::AdditiveCone", name)
        oc.setExpression("Radius1", P("SaddleRo1")); oc.setExpression("Radius2", P("SaddleRo0"))
        oc.setExpression("Height", P("SaddleLength"))
        oc.Placement.Rotation = rot_y
        b.place(oc, P("SaddleAxisX"), P("SaddleY1"), P("SaddleAxisZ"))
        return oc

    def inner_cone(bd, name):
        ic = prim(bd, "PartDesign::SubtractiveCone", name)
        ic.setExpression("Radius1", "%s - %s * %s / 2" % (P("SaddleRi1"), P("TaperSlope"), P("Big")))
        ic.setExpression("Radius2", "%s + %s * %s / 2" % (P("SaddleRi0"), P("TaperSlope"), P("Big")))
        ic.setExpression("Height", "%s + 2 * %s" % (P("SaddleLength"), P("Big")))
        ic.Placement.Rotation = rot_y
        b.place(ic, P("SaddleAxisX"), "%s + %s" % (P("SaddleY1"), P("Big")), P("SaddleAxisZ"))
        return ic

    def half_space(bd, name, above):
        hb = prim(bd, "PartDesign::SubtractiveBox", name)
        hb.setExpression("Length", "2 * %s + 2 * %s" % (P("SaddleRo0"), P("Big")))
        hb.setExpression("Width", "%s + 2 * %s" % (P("SaddleLength"), P("Big")))
        hb.setExpression("Height", "2 * %s" % P("SaddleRo0"))
        z = P("SaddleAxisZ") if above else "%s - 2 * %s" % (P("SaddleAxisZ"), P("SaddleRo0"))
        b.place(hb, "%s - %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), P("Big")),
                "%s - %s" % (P("SaddleY0"), P("Big")), z)
        return hb

    # ---- upper body: floor patch + outer cone above the axis, junction fillet, cavity
    up = mkbody("Saddle_UpperBody")
    slab = prim(up, "PartDesign::AdditiveBox", "Saddle_FloorPatch")
    slab.setExpression("Length", "2 * (%s + 2 * %s)" % (P("SaddleRo0"), R))
    slab.setExpression("Width", "%s + 2 * %s" % (P("SaddleLength"), R))
    slab.setExpression("Height", "%s - %s - %s" % (P("FloorTopZ"), P("Eps"), P("FloorBotZ")))
    b.place(slab, "%s - %s - 2 * %s" % (P("SaddleAxisX"), P("SaddleRo0"), R), P("SaddleY0"), P("FloorBotZ"))
    outer_cone(up, "Saddle_OuterConeUpper")
    tb = prim(up, "PartDesign::SubtractiveBox", "Saddle_TrimTop")
    tb.setExpression("Length", "2 * %s + 2 * %s" % (P("SaddleRo0"), P("Big")))
    tb.setExpression("Width", "%s + 2 * %s" % (P("SaddleLength"), P("Big")))
    tb.setExpression("Height", "2 * %s" % P("SaddleRo0"))
    b.place(tb, "%s - %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), P("Big")),
            "%s - %s" % (P("SaddleY0"), P("Big")), "%s - %s" % (P("FloorTopZ"), P("Eps")))
    lowcut = half_space(up, "Saddle_UpperCutBelowAxis", above=False)
    doc.recompute()
    zb = s.FloorBotZ.Value
    sh = lowcut.Shape
    # junction = the two cone/floor-underside intersection curves (sides only)
    jn = _edge_names(sh, lambda e: abs(e.BoundBox.ZMax - zb) < 1e-6 and abs(e.BoundBox.ZMin - zb) < 1e-6
                     and e.Curve.__class__.__name__ not in ("Line", "Circle"))
    ffil = up.newObject("PartDesign::Fillet", "Saddle_FloorFillet")
    ffil.Base = (lowcut, jn)
    ffil.setExpression("Radius", R)
    ffil.Refine = False
    b.new.append(ffil)
    icu = inner_cone(up, "Saddle_InnerConeUpper")
    up.Tip = icu
    doc.recompute()

    # ---- shell body: full shell (trimmed under the floor top), opening, lip fillets;
    #      contains no floor geometry, so its topology does not depend on the floor
    lo = mkbody("Saddle_LowerBody")
    outer_cone(lo, "Saddle_OuterConeLower")
    inner_cone(lo, "Saddle_InnerConeLower")
    tl = prim(lo, "PartDesign::SubtractiveBox", "Saddle_ShellTrimTop")
    tl.setExpression("Length", "2 * %s + 2 * %s" % (P("SaddleRo0"), P("Big")))
    tl.setExpression("Width", "%s + 2 * %s" % (P("SaddleLength"), P("Big")))
    tl.setExpression("Height", "2 * %s" % P("SaddleRo0"))
    b.place(tl, "%s - %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), P("Big")),
            "%s - %s" % (P("SaddleY0"), P("Big")), "(%s + %s) / 2" % (P("FloorTopZ"), P("FloorBotZ")))
    sw = prim(lo, "PartDesign::SubtractiveWedge", "Saddle_Opening")
    D = "(%s + %s)" % (P("SaddleRo0"), P("Big"))
    Hh = "%s * tan(90 - %s)" % (D, P("SaddleLipAngle"))
    Ln = "(%s + 2 * %s)" % (P("SaddleLength"), P("Big"))
    for k, v in (("Xmin", "-" + Hh), ("Xmax", Hh), ("Ymin", "0 mm"), ("Ymax", D), ("Zmin", "0 mm"),
                 ("Zmax", Ln), ("X2min", "0 mm"), ("X2max", "0 mm"), ("Z2min", "0 mm"), ("Z2max", Ln)):
        sw.setExpression(k, v)
    sw.Placement.Rotation = App.Rotation(App.Vector(1, 0, 0), 90)
    b.place(sw, P("SaddleAxisX"), "%s + %s" % (P("SaddleY1"), P("Big")), "%s - %s" % (P("SaddleAxisZ"), D))
    doc.recompute()
    fsh = sw.Shape
    az = s.SaddleAxisZ.Value

    def lip(e):
        # the 4 long lip edges (entirely below the cylinder axis).  The short lip-end
        # edges are left sharp: their corner blends raised the model tolerance to
        # ~4e-3 mm (FreeCAD 1.1.4), which degraded the STEP export.
        return e.BoundBox.ZMax < az - 1e-6 and _sharp(fsh, e) and e.Length > 0.5 * s.SaddleLength.Value
    ln = _edge_names(fsh, lip)
    efil = lo.newObject("PartDesign::Fillet", "Saddle_EdgeFillet")
    efil.Base = (sw, ln)
    efil.setExpression("Radius", P("SaddleEdgeR"))
    efil.Refine = False
    b.new.append(efil)
    lo.Tip = efil
    doc.recompute()
    joined = b.fuse("Saddle_Joined", [up, lo], ga, refine=True)
    doc.recompute()
    doc.Fin_03_AddSaddle.Shapes = [doc.Fin_02_CutCylinderEnvelope, joined]
    log.append("saddle rebuilt in PartDesign (upper/lower bodies); junction fillet edges %s ; lip fillet edges %d" % (jn, len(ln)))

    # ---- 4. new drainage slots ----------------------------------------------
    g = gslots
    hw, fr = P("DrainSlotHalfW"), P("DrainSlotFilletR")
    thru = b.slotX("DrainSlot_Through", hw, "%s - %s" % (P("FloorBotZ"), P("Eps")),
                   "%s + 2 * %s" % (P("FloorThk"), P("Eps")), g)
    tb = b.ringX("DrainSlotTopEdge_Band", "%s + %s" % (hw, fr), "%s - %s" % (hw, P("Eps")),
                 "%s - %s" % (P("FloorTopZ"), fr), "%s + %s" % (fr, P("Eps")), g)
    tt = b.tubeX("DrainSlotTopEdge_Tube", "%s + %s" % (hw, fr), fr, "%s - %s" % (P("FloorTopZ"), fr), g)
    tcut = b.cut("DrainSlotTopEdge_Cutter", tb, tt, g)
    bb_ = b.ringX("DrainSlotBotEdge_Band", "%s + %s" % (hw, fr), "%s - %s" % (hw, P("Eps")),
                  "%s - %s" % (P("FloorBotZ"), P("Eps")), "%s + %s" % (fr, P("Eps")), g)
    bt = b.tubeX("DrainSlotBotEdge_Tube", "%s + %s" % (hw, fr), fr, "%s + %s" % (P("FloorBotZ"), fr), g)
    bcut = b.cut("DrainSlotBotEdge_Cutter", bb_, bt, g)
    import Draft
    App.setActiveDocument(doc.Name)          # Draft creates objects in the active document
    arrays = {}
    for key, master in (("Through", thru), ("TopEdges", tcut), ("BottomEdges", bcut)):
        arr = Draft.make_ortho_array(master, v_x=App.Vector(25.4, 0, 0), v_y=App.Vector(0, 25.4, 0),
                                     v_z=App.Vector(0, 0, 25.4), n_x=2, n_y=1, n_z=1, use_link=False)
        arr.Label = "DrainSlots_%s" % key
        arr.Fuse = False
        g.addObject(arr)
        arr.setExpression("NumberX", P("DrainSlotCount"))
        arr.setExpression(".IntervalX.x", P("DrainSlotPitch"))
        arr.setExpression(".Placement.Base.x", P("DrainSlotLeftX"))
        b.new.append(arr)
        arrays[key] = arr
    fin7.Tool = arrays["Through"]
    fin8.Tool = arrays["TopEdges"]
    fin9.Tool = arrays["BottomEdges"]
    doc.recompute()
    log.append("new slots built")
    log.append(rebuild_sleeve_fillet(doc))

    # ---- 5. notes, visibility -----------------------------------------------
    for o in b.new:
        try:
            o.Visibility = False
            if App.GuiUp:
                o.ViewObject.Visibility = False
        except Exception:
            pass
    if App.GuiUp:
        doc.ShelfSolid.ViewObject.Visibility = True
    notes = doc.getObject("ModelNotes")
    if notes:
        notes.Text = notes.Text + V2_NOTES
    return log


def rebuild_sleeve_fillet(doc):
    """Replace the V1 sleeve-to-floor fillet (Part band minus torus) with a
    PartDesign fillet in a local body (sleeve cylinder + floor patch).  The V1
    construction is valid natively but its STEP translation fails the
    solid-level validity check; the PartDesign fillet round-trips cleanly."""
    b = Bld(doc)
    gf = _group(doc, "_Fillets")
    f1 = doc.Fin_01_AddFloorRimSleeve
    f1.Shapes = [o for o in f1.Shapes if o.Name != "SleeveFloorFillet"]
    for n in ("SleeveFloorFillet", "SleeveFillet_Torus", "SleeveFillet_Ring", "SleeveFillet_RingIn", "SleeveFillet_RingOut"):
        if doc.getObject(n):
            doc.removeObject(n)
    bd = doc.addObject("PartDesign::Body", "Sleeve_FilletBody")
    gf.addObject(bd)

    def prim(typ, name):
        o = bd.newObject(typ, name)
        try:
            o.MapMode = "Deactivated"
        except Exception:
            pass
        o.Refine = False
        return o
    pad = "(%s + 2 * %s)" % (P("SleeveOR"), P("SleeveFilletR"))
    fp = prim("PartDesign::AdditiveBox", "Sleeve_FloorPatch")
    fp.setExpression("Length", "2 * %s" % pad); fp.setExpression("Width", "2 * %s" % pad)
    fp.setExpression("Height", "%s - %s" % (P("FloorTopZ"), P("FloorBotZ")))
    b.place(fp, "%s - %s" % (P("SleeveX"), pad), "%s - %s" % (P("SleeveY"), pad), P("FloorBotZ"))
    cy = prim("PartDesign::AdditiveCylinder", "Sleeve_AboveFloor")
    cy.setExpression("Radius", P("SleeveOR"))
    cy.setExpression("Height", "%s - %s" % (P("SleeveTopZ"), P("FloorBotZ")))
    b.place(cy, P("SleeveX"), P("SleeveY"), P("FloorBotZ"))
    doc.recompute()
    zt = doc.getObject(SS).FloorTopZ.Value
    ro = doc.getObject(SS).SleeveOR.Value
    jn = _edge_names(cy.Shape, lambda e: e.Curve.__class__.__name__ == "Circle"
                     and abs(e.BoundBox.ZMax - zt) < 1e-6 and abs(e.Curve.Radius - ro) < 1e-6)
    fl = bd.newObject("PartDesign::Fillet", "Sleeve_FloorFillet")
    fl.Base = (cy, jn)
    fl.setExpression("Radius", P("SleeveFilletR"))
    fl.Refine = False
    bd.Tip = fl
    f1.Shapes = list(f1.Shapes) + [bd]
    doc.recompute()
    for o in [bd, fp, cy, fl]:
        try:
            o.Visibility = False
            if App.GuiUp:
                o.ViewObject.Visibility = False
        except Exception:
            pass
    return "sleeve fillet rebuilt in PartDesign (edge %s)" % jn


V2_NOTES = """

---- Version 2 (Phase 1B) changes ----
 * SaddleCrownZ (was CrownZ) = -0.650 in = floor underside -> full 0.150
   floor over the crown.  The saddle's outer crown (-0.450) is still trimmed
   just below the floor top.
 * 05_TaperedSaddle: rebuilt as two PartDesign bodies fused by
   Part::MultiFuse 'Saddle_Joined':
   Saddle_UpperBody: AdditiveBox Saddle_FloorPatch (lies inside the floor)
     + AdditiveCone outer - SubtractiveBox Saddle_TrimTop (FloorTopZ - Eps)
     - SubtractiveBox below the axis -> Saddle_FloorFillet
     (R = SaddleFloorFilletR on the two side cone/floor-underside junctions)
     - SubtractiveCone inner (cylinder + clearance, on the taper).
   Saddle_LowerBody: AdditiveCone outer - SubtractiveCone inner - trim box at
     mid-floor depth (inside the floor) - SubtractiveWedge Saddle_Opening (apex on axis, faces at
     -/+SaddleLipAngle; requires SaddleWrap > 180) -> Saddle_EdgeFillet
     (R = SaddleEdgeR on the 4 long lip edges; lip ends sharp).
   The shell body holds no floor geometry, so the lip-fillet references do not
   depend on whether the cavity crown cuts into the floor (toponaming).
   Not filleted: the front end-face/floor junction (the fillet would hang
   across the cavity mouth) and the saddle end arcs.
   Reason for the rebuild: Part boolean features apply automatic fuzzy
   tolerances that make PartDesign fillets on their output invalid.
 * 07_Fillets: the sleeve-to-floor fillet is now a PartDesign fillet
   (Sleeve_FilletBody: floor patch + sleeve cylinder, R = SleeveFilletR).
   The V1 band-minus-torus construction was valid natively but its STEP
   export failed the solid-level validity check on re-import.
 * 06_DrainageSlots: 2 X-oriented slots.  Masters at X=0, repeated by Draft
   ortho arrays: NumberX = DrainSlotCount, first at DrainSlotLeftX,
   pitch DrainSlotPitch (last at DrainSlotRightX).  DrainSlotCount >= 2.
"""


def build_v2(doc_name="ShowerShelf_3Bottle_V2"):
    """Build Version 1 from scratch, then apply the Phase 1B migration."""
    doc = build(doc_name)
    migrate(doc)
    doc.recompute()
    return doc




# ======================= PHASE 1C MIGRATION (V2 -> V3) =======================
"""
Applies the Phase 1C changes to an open V2 model *in place*:

  1. Reinforcing arms.  The rear rim on each side of the sleeve continues
     past its tangent point as a circular arc of the same cross-section
     (thickness ArmThk = RimThk, full-round top) that curves forward into the
     sleeve and meets the sleeve OD at a right angle (arm centreline is a
     circle orthogonal to the sleeve OD circle).  Both arm faces blend into
     the sleeve OD with plan-view radius ArmSleeveFilletR; all new wall/floor
     corners get floor fillets, all new top edges are rounded.  The right arm
     is a mirror of the left arm about X = SleeveX.
  2. Rear drainage opening.  Between the two arm tangent points the rear rim
     (and its floor fillet) is removed down to the floor top (Z = FloorTopZ =
     -0.500 in).  The floor itself (FloorThk) is untouched: no through-opening.
  3. Sleeve top outer edge: rounded with SleeveTopEdgeR outside the two arm
     entry zones (needed so the arm/web top rounds end tangent to the sleeve).

Plan-view construction (left arm, all derived in the spreadsheet):
    a  = DrainOpeningWidth / 2        y0 = ArmThk / 2       b = SleeveY - y0
    ArmR = (a^2 + b^2 - SleeveOR^2) / (2 b)        centre C = (SleeveX - a, y0 + ArmR)
  => arm centreline is tangent to the rim centreline at X = SleeveX - a and is
     orthogonal to the sleeve OD.  Junction circles J (radius rj) satisfy
     |JC| = ArmRout + rj (rear/convex side) or ArmRin - rj (pocket/concave side)
     and |JS| = SleeveOR + rj.
Everything is built from Part primitives with expressions + booleans; no
topological-name references are used, so the arms recompute for any valid
parameter set (see the Chk* cells).
"""



# (alias, expression, display unit, category, description)
V3_PARAMS = [
    ("# Reinforcing arms and rear drain opening (V3)", None, None, None, None),
    ("DrainOpeningWidth", "=3.000 in", "in", "ASSUMED",
     "Rear drain opening width = distance between the two arm tangent points on the rear rim"),
    ("ArmThk", "=RimThk", "in", "CALCULATED",
     "Arm wall thickness (= rim; keep equal for a step-free rim-to-arm transition)"),
    ("ArmSleeveFilletR", "=0.1875 in", "in", "ASSUMED",
     "Plan-view junction radius between each arm face and the sleeve OD"),
    ("ArmFloorFilletR", "=RimFilletR", "in", "CALCULATED", "Arm / junction wall-to-floor fillet radius (= rim)"),
    ("ArmBullnoseR", "=RimBullnoseR", "in", "CALCULATED", "Arm / junction top edge round (= rim bullnose)"),
    ("SleeveTopEdgeR", "=ArmBullnoseR", "in", "ASSUMED",
     "Sleeve top OUTER edge round (new in V3; outside the arm entry zones)"),
    ("OpeningZ", "=FloorTopZ", "in", "CALCULATED", "Rear opening sill elevation = floor top"),
    ("ArmAngMargin", "=5 deg", "deg", "TOOL", "Angular over-run of torus tools beyond their cutter sectors"),
    ("ArmHalfOpen", "=DrainOpeningWidth / 2", "in", "CALCULATED", "a = half opening width"),
    ("ArmYc0", "=ArmThk / 2", "in", "CALCULATED", "Arm/rim centreline Y at the tangent point"),
    ("ArmB", "=SleeveY - ArmYc0", "in", "CALCULATED", "b = sleeve centre Y above the rim centreline"),
    ("ArmR", "=(ArmHalfOpen ^ 2 + ArmB ^ 2 - SleeveOR ^ 2) / (2 * ArmB)", "in", "CALCULATED",
     "Arm centreline radius (tangent to rim, orthogonal to sleeve OD)"),
    ("ArmCxL", "=SleeveX - ArmHalfOpen", "in", "CALCULATED", "Left arm centre X (= left tangent point X)"),
    ("ArmCxR", "=SleeveX + ArmHalfOpen", "in", "CALCULATED", "Right arm centre X (= right tangent point X)"),
    ("ArmCy", "=ArmYc0 + ArmR", "in", "CALCULATED", "Arm centre Y"),
    ("ArmRin", "=ArmR - ArmThk / 2", "in", "CALCULATED", "Arm pocket-side (concave) face radius"),
    ("ArmRout", "=ArmR + ArmThk / 2", "in", "CALCULATED", "Arm rear-side (convex) face radius"),
    ("ArmCS", "=sqrt(ArmHalfOpen ^ 2 + (SleeveY - ArmCy) ^ 2)", "in", "CALCULATED", "Arm centre to sleeve centre"),
    ("ArmPhiCS", "=atan2(SleeveY - ArmCy; ArmHalfOpen)", "deg", "CALCULATED",
     "Direction arm centre -> sleeve centre (arm sector end, inside the bore)"),
    ("ArmSpan", "=ArmPhiCS + 90 deg", "deg", "CALCULATED", "Arm band sweep from the tangent point"),
    ("JS", "=SleeveOR + ArmSleeveFilletR", "in", "CALCULATED", "Junction circle centre to sleeve centre"),
    ("JoC", "=ArmRout + ArmSleeveFilletR", "in", "CALCULATED", "Rear junction centre to arm centre"),
    ("JoAlpha", "=acos((JoC ^ 2 + ArmCS ^ 2 - JS ^ 2) / (2 * JoC * ArmCS))", "deg", "CALCULATED", "Rear junction angle at C"),
    ("JoAng", "=ArmPhiCS - JoAlpha", "deg", "CALCULATED", "Rear junction direction from C (= tangent point T1)"),
    ("JoX", "=ArmCxL + JoC * cos(JoAng)", "in", "CALCULATED", "Rear (convex-side) junction centre X, left"),
    ("JoY", "=ArmCy + JoC * sin(JoAng)", "in", "CALCULATED", "Rear (convex-side) junction centre Y"),
    ("JiC", "=ArmRin - ArmSleeveFilletR", "in", "CALCULATED", "Pocket junction centre to arm centre"),
    ("JiAlpha", "=acos((JiC ^ 2 + ArmCS ^ 2 - JS ^ 2) / (2 * JiC * ArmCS))", "deg", "CALCULATED", "Pocket junction angle at C"),
    ("JiAng", "=ArmPhiCS - JiAlpha", "deg", "CALCULATED", "Pocket junction direction from C (= tangent point T1)"),
    ("JiX", "=ArmCxL + JiC * cos(JiAng)", "in", "CALCULATED", "Pocket (concave-side) junction centre X, left"),
    ("JiY", "=ArmCy + JiC * sin(JiAng)", "in", "CALCULATED", "Pocket (concave-side) junction centre Y"),
    ("JoDirT1", "=JoAng + 180 deg", "deg", "CALCULATED", "Rear junction: direction J -> arm tangent point"),
    ("JoDirT2", "=atan2(SleeveY - JoY; SleeveX - JoX)", "deg", "CALCULATED", "Rear junction: direction J -> sleeve tangent point"),
    ("JoN", "=(JoDirT2 - JoDirT1) - 360 deg * floor((JoDirT2 - JoDirT1) / (360 deg))", "deg", "CALCULATED", "Normalised T1->T2 sweep"),
    ("JoStart", "=JoN <= 180 deg ? JoDirT1 : JoDirT2", "deg", "CALCULATED", "Rear junction arc start"),
    ("JoSpan", "=JoN <= 180 deg ? JoN : 360 deg - JoN", "deg", "CALCULATED", "Rear junction arc sweep"),
    ("JiDirT1", "=JiAng", "deg", "CALCULATED", "Pocket junction: direction J -> arm tangent point"),
    ("JiDirT2", "=atan2(SleeveY - JiY; SleeveX - JiX)", "deg", "CALCULATED", "Pocket junction: direction J -> sleeve tangent point"),
    ("JiN", "=(JiDirT2 - JiDirT1) - 360 deg * floor((JiDirT2 - JiDirT1) / (360 deg))", "deg", "CALCULATED", "Normalised T1->T2 sweep"),
    ("JiStart", "=JiN <= 180 deg ? JiDirT1 : JiDirT2", "deg", "CALCULATED", "Pocket junction arc start"),
    ("JiSpan", "=JiN <= 180 deg ? JiN : 360 deg - JiN", "deg", "CALCULATED", "Pocket junction arc sweep"),
    ("ArmConvexSpan", "=JoAng + 90 deg", "deg", "CALCULATED", "Rear-face round/fillet sweep (tangent point -> T1)"),
    ("ArmConcaveSpan", "=JiAng + 90 deg", "deg", "CALCULATED", "Pocket-face round/fillet sweep (tangent point -> T1)"),
    ("SlvPhiO", "=atan2(JoY - SleeveY; JoX - SleeveX)", "deg", "CALCULATED", "Sleeve angle of left rear junction tangent point"),
    ("SlvPhiI", "=atan2(JiY - SleeveY; JiX - SleeveX)", "deg", "CALCULATED", "Sleeve angle of left pocket junction tangent point"),
    ("SlvRearSpan", "=-180 deg - 2 * SlvPhiO", "deg", "CALCULATED", "Sleeve top round, rear arc between the arms"),
    ("SlvFrontStart", "=-180 deg - SlvPhiI", "deg", "CALCULATED", "Sleeve top round, front arc start (right arm)"),
    ("SlvFrontSpan", "=540 deg + 2 * SlvPhiI", "deg", "CALCULATED", "Sleeve top round, front arc sweep"),
    ("OpenCutY", "=RimThk + RimFilletR + Eps", "in", "TOOL", "Rear opening cutter depth (rim + rim fillet)"),
    ("ChkArmRearGap", "=2 * (SleeveX - JoX) - 2 * ArmSleeveFilletR - 0.050 in", "in", "CALCULATED",
     "CHECK > 0: gap between L/R rear junction radii behind the sleeve, minus 0.050 in minimum (tested limit)"),
    ("ChkOpenVsSleeve", "=SleeveY - SleeveOR - SleeveFilletR - OpenCutY", "in", "CALCULATED",
     "CHECK > 0: opening cutter clear of sleeve + sleeve fillet"),
    ("ChkArmVsEndArc", "=ArcCxR - ArmCxR", "in", "CALCULATED", "CHECK > 0: arm roots on the straight rear rim"),
    ("ChkArmRound", "=ArmThk / 2 - ArmBullnoseR", "in", "CALCULATED", "CHECK >= 0: arm round fits the arm"),
    ("ChkJunctionFillet", "=ArmSleeveFilletR - 2 * ArmFloorFilletR", "in", "CALCULATED",
     "CHECK > 0: junction radius leaves room for its floor fillet"),
    ("ChkPocketJunction", "=JiC - ArmSleeveFilletR", "in", "CALCULATED", "CHECK > 0: pocket junction radius fits inside arm curve"),
]


class Bld3:
    def __init__(self, doc, group):
        self.doc = doc
        self.g = group
        self.new = []

    def add(self, typ, name):
        o = self.doc.addObject(typ, name)
        self.g.addObject(o)
        self.new.append(o)
        return o

    def place(self, o, x, y, z):
        o.setExpression(".Placement.Base.x", x)
        o.setExpression(".Placement.Base.y", y)
        o.setExpression(".Placement.Base.z", z)

    def cyl(self, n, r, h, x, y, z, start=None, span=None):
        o = self.add("Part::Cylinder", n)
        o.setExpression("Radius", r)
        o.setExpression("Height", h)
        if span is not None:
            o.setExpression("Angle", span)
            o.setExpression(".Placement.Rotation", "rotation(vector(0; 0; 1); %s)" % start)
        self.place(o, x, y, z)
        return o

    def torus(self, n, R1, R2, x, y, z, start, span):
        o = self.add("Part::Torus", n)
        o.setExpression("Radius1", R1)
        o.setExpression("Radius2", R2)
        o.setExpression("Angle3", "%s + 2 * %s" % (span, P("ArmAngMargin")))
        o.setExpression(".Placement.Rotation",
                        "rotation(vector(0; 0; 1); %s - %s)" % (start, P("ArmAngMargin")))
        self.place(o, x, y, z)
        return o

    def box(self, n, L, W, H, x, y, z):
        o = self.add("Part::Box", n)
        o.setExpression("Length", L)
        o.setExpression("Width", W)
        o.setExpression("Height", H)
        self.place(o, x, y, z)
        return o

    def cut(self, n, base, tool):
        o = self.add("Part::Cut", n)
        o.Base = base
        o.Tool = tool
        o.Refine = False
        return o

    def fuse(self, n, objs):
        o = self.add("Part::MultiFuse", n)
        o.Shapes = objs
        o.Refine = False
        return o

    def common(self, n, objs):
        o = self.add("Part::MultiCommon", n)
        o.Shapes = objs
        return o

    # ring sector (r_in < r_out) around (x, y)
    def ring(self, n, x, y, r_out, r_in, z0, h, start=None, span=None):
        o = self.cyl(n + "_Out", r_out, h, x, y, z0, start, span)
        i = self.cyl(n + "_In", r_in, "%s + 2 * %s" % (h, P("Eps")), x, y, "%s - %s" % (z0, P("Eps")))
        return self.cut(n, o, i)

    # top-edge round cutter for a vertical cylindrical face of radius rf about (x, y).
    # material_inside=True: material at r < rf (convex face).  Top at Z = 0.
    def top_round(self, n, x, y, rface, rb, material_inside, start, span):
        z0 = "-%s" % rb
        h = "%s + %s" % (rb, P("Eps"))
        if material_inside:
            band = self.ring(n + "_Band", x, y, "%s + %s" % (rface, P("Eps")),
                             "%s - %s" % (rface, rb), z0, h, start, span)
            tc = "%s - %s" % (rface, rb)
        else:
            band = self.ring(n + "_Band", x, y, "%s + %s" % (rface, rb),
                             "%s - %s" % (rface, P("Eps")), z0, h, start, span)
            tc = "%s + %s" % (rface, rb)
        tor = self.torus(n + "_Torus", tc, rb, x, y, z0, start, span)
        return self.cut(n, band, tor)

    # wall-to-floor fillet (additive) for a vertical cylindrical face of radius rface.
    def floor_fillet(self, n, x, y, rface, rf, material_inside, start, span):
        zt = P("FloorTopZ")
        if material_inside:      # free space outside the face
            band = self.ring(n + "_Band", x, y, "%s + %s" % (rface, rf), rface, zt, rf, start, span)
            tc = "%s + %s" % (rface, rf)
        else:                    # free space inside the face
            band = self.ring(n + "_Band", x, y, rface, "%s - %s" % (rface, rf), zt, rf, start, span)
            tc = "%s - %s" % (rface, rf)
        tor = self.torus(n + "_Torus", tc, rf, x, y, "%s + %s" % (zt, rf), start, span)
        return self.cut(n, band, tor)


def _set_row3(s, r, alias, expr, unit, cat, desc):
    if expr is None:
        s.set("A%d" % r, alias.lstrip("# ").upper())
        return
    s.set("A%d" % r, alias)
    s.set("B%d" % r, expr)
    s.setAlias("B%d" % r, alias)
    if unit == "in":
        s.setDisplayUnit("B%d" % r, "in")
    s.set("C%d" % r, unit or "")
    s.set("D%d" % r, cat)
    s.set("E%d" % r, desc)


def _group3(doc, suffix):
    for o in doc.Objects:
        if o.TypeId == "App::DocumentObjectGroup" and o.Label.endswith(suffix):
            return o
    raise RuntimeError("group *%s not found" % suffix)


def add_parameters_v3(doc):
    s = doc.getObject(SS)
    if s.getCellFromAlias("DrainOpeningWidth"):
        raise RuntimeError("V3 parameters already present")
    # insert the new section in front of the 'MODELLING TOLERANCES' block
    r_eps = int(s.getCellFromAlias("Eps")[1:])
    r0 = r_eps - 1                       # header row of the tolerance block
    n = len(V3_PARAMS) + 1               # + blank spacer row
    s.insertRows(str(r0), n)
    doc.recompute()
    for k, row in enumerate(V3_PARAMS):
        _set_row3(s, r0 + k, *row)
    # second pass so forward references bind
    for k, row in enumerate(V3_PARAMS):
        if row[1] is not None:
            s.set("B%d" % (r0 + k), s.getContents("B%d" % (r0 + k)))
    doc.recompute()
    return s


def migrate_v3(doc):
    App.setActiveDocument(doc.Name)
    s = add_parameters_v3(doc)
    grp = doc.addObject("App::DocumentObjectGroup", "ArmsAndRearOpening")
    grp.Label = "_10_ArmsAndRearOpening"
    b = Bld3(doc, grp)
    E = P("Eps")
    zt = P("FloorTopZ")
    hwall = "%s + %s" % (P("RimHeight"), E)             # FloorTopZ - Eps .. 0
    zw = "%s - %s" % (zt, E)
    cx, cy = P("ArmCxL"), P("ArmCy")
    sx, sy = P("SleeveX"), P("SleeveY")
    rj = P("ArmSleeveFilletR")
    rf = P("ArmFloorFilletR")
    rb = P("ArmBullnoseR")

    # ---- rear opening: remove rim + rim fillet between the arm tangent points
    obox = b.box("RearOpening_Cutter", "2 * %s" % P("ArmHalfOpen"),
                 "%s + %s" % (P("OpenCutY"), P("Big")),
                 "%s - %s" % (P("Big"), P("OpeningZ")),
                 cx, "-%s" % P("Big"), P("OpeningZ"))
    obox.Label = "RearOpening_Cutter (Z = OpeningZ)"
    # trim box for the straight-rim bullnose cutters inside the opening span
    tbox = b.box("RearOpening_BullnoseTrim", "2 * %s" % P("ArmHalfOpen"),
                 "%s + %s" % (P("ShelfYc"), P("Big")),
                 "2 * %s + %s" % (P("Big"), P("RimBullnoseR")),
                 cx, "-%s" % P("Big"), "-%s - %s" % (P("RimBullnoseR"), P("Big")))

    # ---- left arm additive pieces --------------------------------------------
    arm = b.ring("ArmL_Band", cx, cy, P("ArmRout"), P("ArmRin"), zw, hwall, "-90 deg", P("ArmSpan"))
    # junction webs: (annulus at the face) x (disk S, JS) x (fan of J) - disk J
    wo_ann = b.ring("ArmL_WebRear_Ann", cx, cy, "%s + %s" % (P("ArmRout"), rj),
                    "%s - %s" % (P("ArmRout"), E), zw, hwall)
    wi_ann = b.ring("ArmL_WebPocket_Ann", cx, cy, "%s + %s" % (P("ArmRin"), E),
                    "%s - %s" % (P("ArmRin"), rj), zw, hwall)
    webs = []
    for tag, ann, jx, jy, st, sp in (("Rear", wo_ann, "JoX", "JoY", "JoStart", "JoSpan"),
                                     ("Pocket", wi_ann, "JiX", "JiY", "JiStart", "JiSpan")):
        dS = b.cyl("ArmL_Web%s_DiskS" % tag, P("JS"), hwall, sx, sy, zw)
        fan = b.cyl("ArmL_Web%s_Fan" % tag, P("JS"), hwall, P(jx), P(jy), zw, P(st), P(sp))
        # (MultiCommon with >2 shapes intersects the first with the UNION of the rest,
        #  so intersect pairwise)
        com0 = b.common("ArmL_Web%s_AnnDisk" % tag, [ann, dS])
        com = b.common("ArmL_Web%s_Region" % tag, [com0, fan])
        dJ = b.cyl("ArmL_Web%s_DiskJ" % tag, rj, "%s + 2 * %s" % (hwall, E), P(jx), P(jy), "%s - %s" % (zw, E))
        webs.append(b.cut("ArmL_Web%s" % tag, com, dJ))
    # floor fillets
    f_pocket = b.floor_fillet("ArmL_FloorFilletPocket", cx, cy, P("ArmRin"), rf, False,
                              "-90 deg", P("ArmConcaveSpan"))
    f_rear0 = b.floor_fillet("ArmL_FloorFilletRearRaw", cx, cy, P("ArmRout"), rf, True,
                             "-90 deg", P("ArmConvexSpan"))
    ytrim = b.box("ArmL_FloorFilletRear_TrimY", "2 * %s + 2 * %s" % (P("ArmRout"), P("Big")),
                  "%s + %s" % (P("ShelfYc"), P("Big")), "%s + 2 * %s" % (rf, E),
                  "%s - %s - %s" % (cx, P("ArmRout"), P("Big")), "0 mm", "%s - %s" % (zt, E))
    f_rear = b.common("ArmL_FloorFilletRear", [f_rear0, ytrim])
    f_wo = b.floor_fillet("ArmL_WebRear_FloorFillet", P("JoX"), P("JoY"), rj, rf, False,
                          P("JoStart"), P("JoSpan"))
    f_wi = b.floor_fillet("ArmL_WebPocket_FloorFillet", P("JiX"), P("JiY"), rj, rf, False,
                          P("JiStart"), P("JiSpan"))
    addL = b.fuse("ArmL_Additive", [arm] + webs + [f_pocket, f_rear, f_wo, f_wi])
    # Refine merges the coplanar top/bottom faces of arm, webs and fillets; without
    # it the seam edges left on the Z = 0 plane (some < 0.05 mm long, length varies
    # with the parameters) made the later top-round cuts fail for some values.
    addL.Refine = True
    addR = b.add("Part::Mirroring", "ArmR_Additive")
    addR.Source = addL
    addR.Normal = App.Vector(1, 0, 0)
    addR.setExpression(".Base.x", sx)
    addR.Label = "ArmR_Additive (mirror of left about X = SleeveX)"

    # ---- top-edge rounds ------------------------------------------------------
    t_rear = b.top_round("ArmL_TopRoundRear", cx, cy, P("ArmRout"), rb, True, "-90 deg", P("ArmConvexSpan"))
    t_pock = b.top_round("ArmL_TopRoundPocket", cx, cy, P("ArmRin"), rb, False, "-90 deg", P("ArmConcaveSpan"))
    t_wo = b.top_round("ArmL_WebRear_TopRound", P("JoX"), P("JoY"), rj, rb, False, P("JoStart"), P("JoSpan"))
    t_wi = b.top_round("ArmL_WebPocket_TopRound", P("JiX"), P("JiY"), rj, rb, False, P("JiStart"), P("JiSpan"))
    topL = b.fuse("ArmL_TopRounds", [t_rear, t_pock, t_wo, t_wi])
    topR = b.add("Part::Mirroring", "ArmR_TopRounds")
    topR.Source = topL
    topR.Normal = App.Vector(1, 0, 0)
    topR.setExpression(".Base.x", sx)
    srb = P("SleeveTopEdgeR")
    s_rear = b.top_round("SleeveTop_RoundRear", sx, sy, P("SleeveOR"), srb, True, P("SlvPhiO"), P("SlvRearSpan"))
    s_front = b.top_round("SleeveTop_RoundFront", sx, sy, P("SleeveOR"), srb, True,
                          P("SlvFrontStart"), P("SlvFrontSpan"))
    tops = b.fuse("V3_TopRounds_Tool", [topL, topR, s_rear, s_front])

    # ---- re-wire the final chain ---------------------------------------------
    gf = _group3(doc, "FinalManufacturingSolid")
    f03 = doc.getObject("Fin_03_AddSaddle")
    f04 = doc.getObject("Fin_04_CutSleeveBore")
    f05 = doc.getObject("Fin_05_CutBullnoseOuter")
    f06 = doc.getObject("Fin_06_CutBullnoseInner")
    f07 = doc.getObject("Fin_07_CutSlotsThrough")
    c_open = b.cut("Fin_03a_CutRearOpening", f03, obox)
    a_arms = b.fuse("Fin_03b_AddArms", [c_open, addL, addR])
    a_arms.Refine = True        # merge arm / sleeve / floor coplanar faces (see ArmL_Additive)
    f04.Base = a_arms
    bo_t = b.cut("BullnoseOuter_CutterTrimmed", f05.Tool, tbox)
    bi_t = b.cut("BullnoseInner_CutterTrimmed", f06.Tool, tbox)
    f05.Tool = bo_t
    f06.Tool = bi_t
    c_tops = b.cut("Fin_06a_CutArmAndSleeveTopRounds", f06, tops)
    f07.Base = c_tops
    for o in (c_open, a_arms, c_tops):
        grp.removeObject(o)
        gf.addObject(o)
    for o in b.new:
        if o not in (c_open, a_arms, c_tops):
            o.Visibility = False
    doc.recompute()
    notes = doc.getObject("ModelNotes")
    if notes is not None and hasattr(notes, "Text"):
        notes.Text = notes.Text + V3_NOTES
    return b.new


V3_NOTES = """

PHASE 1C (V3) CHANGES
 * 10_ArmsAndRearOpening: reinforcing arms.  Each rear-rim segment continues past
   its tangent point (X = SleeveX -/+ DrainOpeningWidth/2) as a circular arc of
   the rim cross-section (ArmThk, full-round top) that meets the sleeve OD at a
   right angle.  Plan-view junction radii ArmSleeveFilletR on both faces, floor
   fillets ArmFloorFilletR, top rounds ArmBullnoseR.  Right arm = mirror of left.
 * Rear drain opening: rim + rim fillet removed between the tangent points down
   to OpeningZ = FloorTopZ (-0.500 in).  Floor thickness unchanged (0.150 in).
 * Sleeve top outer edge rounded (SleeveTopEdgeR) outside the arm entry zones.
 * Chain: Fin_03 -> Fin_03a_CutRearOpening -> Fin_03b_AddArms -> Fin_04 (bore)
   -> Fin_05/06 (rim bullnose, trimmed out of the opening span)
   -> Fin_06a_CutArmAndSleeveTopRounds -> Fin_07.. (slots) -> ShelfSolid.
 * Keep all Chk* cells positive (see Parameters).
"""


def build_v3(doc_name="ShowerShelf_3Bottle_V3"):
    """Build V1 from scratch, apply the Phase 1B and Phase 1C migrations."""
    doc = build(doc_name)
    migrate(doc)            # Phase 1B (V1 -> V2)
    doc.recompute()
    migrate_v3(doc)         # Phase 1C (V2 -> V3)
    doc.recompute()
    return doc




# ======================= PHASE 3 MIGRATION (V3 -> V4) =======================
"""
Applies the Phase 3 structural changes to an open V3 model *in place*:

  1. Mounting sleeve extended upward: SleeveTopZ = +1.000 in (bore, OD, wall,
     centre and the engagement below the shelf unchanged).  Sleeve top outer
     edge rounded (SleeveTopEdgeR) all round except where the left arm enters.
  2. Rising left rear rim ("S-curve"): from RiseStartX the left rear rim and the
     left arm become one lofted wall (Part::Loft through 11 parametric section
     sketches, sheet 'RiseStations').  The crest follows a reverse-curve
     (two tangent arcs, horizontal tangents at both ends) from Z = 0 to
     Z = SleeveTopZ, measured along the rear face of the rim/arm; it reaches
     full height at arm angle RiseEndAng, just before the arm-to-sleeve
     junction.  Every section has a full-round top (radius = thickness/2) and
     RimFilletR floor flares, so the loft starts with exactly the V3 rim
     section and ends with exactly the V4 junction-zone section.
  3. Left arm thickness: smoothstep from RimThk (0.125 in) at RiseStartX to
     ArmThkL4 = SleeveWall (0.200 in) at RiseEndAng; constant 0.200 in from
     there into the sleeve.  Thickening is on the pocket (bottle) side; the
     rear face keeps the V3 line/arc.  Junction blends to the sleeve
     (ArmSleeveFilletR, R0.1875) are rebuilt for the thicker arm at full
     sleeve height.  The right arm is the unchanged V3 arm (mirror of the V3
     left-arm construction, which is kept in the document for that purpose).
  4. Saddle front end: concave fillet SaddleFrontFilletR between the saddle
     front end face and the floor underside, wrapping the side fillets;
     material over the cylinder envelope (extended forward on the measured
     taper) is removed, so the mating surface and installation path are free.
  5. Saddle-to-floor side fillets: left SaddleFloorFilletR_L, right
     SaddleFloorFilletR (unchanged R0.200).
"""

V4_PARAMS = [
    ("# Phase 3 / V4 structural changes", None, None, None, None),
    ("SleeveExtension", "=SleeveTopZ", "in", "CALCULATED", "Sleeve extension above the rim top (Z = 0); V4 approved +1.000 in"),
    ("RiseStartX", "=(ShelfXmin + SleeveX) / 2", "in", "ASSUMED",
     "Rim S-curve start X on the left rear rim (halfway between left end and sleeve)"),
    ("RiseEndAng", "=-50 deg", "deg", "ASSUMED",
     "Arm angle about the arm centre where the rim reaches full height (-90 deg = rim tangent point)"),
    ("RiseHeight", "=SleeveTopZ", "in", "CALCULATED", "Crest rise: rim top (Z = 0) to sleeve top"),
    ("RiseShape", "=1", "", "ASSUMED",
     "S-curve shape = R1/R2 of the two reverse arcs (1 = symmetric; > 1 moves the steepest point later)"),
    ("RiseLenStraight", "=ArmCxL - RiseStartX", "in", "CALCULATED", "Rise path length on the straight rear rim (along the rear face)"),
    ("RiseLenArc", "=ArmRout * (RiseEndAng + 90 deg) / (180 deg) * pi", "in", "CALCULATED",
     "Rise path length on the arm rear face"),
    ("RiseLength", "=RiseLenStraight + RiseLenArc", "in", "CALCULATED", "S-curve transition length (rear-face path)"),
    ("RiseTheta", "=2 * atan(RiseHeight / RiseLength)", "deg", "CALCULATED", "Arc sweep of each reverse arc"),
    ("RiseRsum", "=RiseLength / sin(RiseTheta)", "in", "CALCULATED", "R1 + R2"),
    ("RiseR1", "=RiseRsum * RiseShape / (1 + RiseShape)", "in", "CALCULATED", "Lower (concave-up) arc radius"),
    ("RiseR2", "=RiseRsum / (1 + RiseShape)", "in", "CALCULATED", "Upper (concave-down) arc radius"),
    ("RiseSm", "=RiseR1 * sin(RiseTheta)", "in", "CALCULATED", "Path position of the inflection point"),
    ("RiseMaxSlope", "=RiseTheta", "deg", "CALCULATED", "Steepest crest slope (at the inflection)"),
    ("ArmThkL4Start", "=RimThk", "in", "CALCULATED", "Left rim/arm thickness at the S-curve start (= rim)"),
    ("ArmThkL4", "=SleeveWall", "in", "APPROVED", "Left arm thickness at the sleeve (= sleeve wall 0.200 in)"),
    ("ArmRinL4", "=ArmRout - ArmThkL4", "in", "CALCULATED", "Left arm pocket-face radius in the junction zone"),
    ("ArmBullnoseRL4", "=ArmThkL4 / 2", "in", "CALCULATED", "Left arm full-round top radius at full height (and junction/sleeve top rounds)"),
    ("JiC4", "=ArmRinL4 - ArmSleeveFilletR", "in", "CALCULATED", "Left pocket junction centre to arm centre (V4)"),
    ("JiAlpha4", "=acos((JiC4 ^ 2 + ArmCS ^ 2 - JS ^ 2) / (2 * JiC4 * ArmCS))", "deg", "CALCULATED", "Pocket junction angle at C (V4)"),
    ("JiAng4", "=ArmPhiCS - JiAlpha4", "deg", "CALCULATED", "Pocket junction direction from C (= tangent point on the arm, V4)"),
    ("JiX4", "=ArmCxL + JiC4 * cos(JiAng4)", "in", "CALCULATED", "Left pocket junction centre X (V4)"),
    ("JiY4", "=ArmCy + JiC4 * sin(JiAng4)", "in", "CALCULATED", "Left pocket junction centre Y (V4)"),
    ("JiDirT2_4", "=atan2(SleeveY - JiY4; SleeveX - JiX4)", "deg", "CALCULATED", "Pocket junction: direction J -> sleeve tangent point"),
    ("JiN4", "=(JiDirT2_4 - JiAng4) - 360 deg * floor((JiDirT2_4 - JiAng4) / (360 deg))", "deg", "CALCULATED", "Normalised sweep"),
    ("JiStart4", "=JiN4 <= 180 deg ? JiAng4 : JiDirT2_4", "deg", "CALCULATED", "Pocket junction arc start (V4)"),
    ("JiSpan4", "=JiN4 <= 180 deg ? JiN4 : 360 deg - JiN4", "deg", "CALCULATED", "Pocket junction arc sweep (V4)"),
    ("SlvPhiI4", "=atan2(JiY4 - SleeveY; JiX4 - SleeveX)", "deg", "CALCULATED", "Sleeve angle of the left pocket junction tangent point (V4)"),
    ("SlvRoundSpan4", "=360 deg - (SlvPhiO - SlvPhiI4)", "deg", "CALCULATED",
     "Sleeve top round sweep at Z = SleeveTopZ (all round except the left arm entry)"),
    ("SaddleFloorFilletR_L", "=0.300 in", "in", "APPROVED",
     "Saddle-to-floor fillet, LEFT side (two-bottle side); right side = SaddleFloorFilletR"),
    ("SaddleFilletRmax", "=max(SaddleFloorFilletR; SaddleFloorFilletR_L)", "in", "CALCULATED", "Larger side fillet (sizes the floor patch)"),
    ("SaddleFrontFilletR", "=0.250 in", "in", "APPROVED",
     "Saddle front end face to floor underside fillet (wraps the side fillets)"),
    ("SaddleFrontExt", "=SaddleFrontFilletR + Eps", "in", "TOOL", "Forward extension of the upper saddle body that carries the front fillet"),
    ("CavityFrontExt", "=Big + SaddleFrontExt", "in", "TOOL", "Forward extension of the cylinder-envelope cutter (on the taper)"),
    ("ChkRiseStart", "=RiseStartX - ArcCxL", "in", "CALCULATED", "CHECK > 0: S-curve starts on the straight rear rim"),
    ("ChkRiseStraight", "=RiseLenStraight", "in", "CALCULATED", "CHECK > 0: S-curve starts left of the arm tangent point"),
    ("ChkRiseEnd", "=min(JoAng; JiAng4) - RiseEndAng", "deg", "CALCULATED",
     "CHECK > 0: full height reached before the arm-to-sleeve junction blends"),
    ("ChkRiseR", "=min(RiseR1; RiseR2) - 0.5 in", "in", "CALCULATED", "CHECK > 0: reverse-arc radii >= 0.5 in (smooth crest)"),
    ("ChkRiseSlope", "=45 deg - RiseTheta", "deg", "CALCULATED",
     "CHECK > 0: steepest crest slope <= 45 deg (steeper rises: lengthen the transition; tested lofts invalid at 55 deg)"),
    ("ChkPocketJunction4", "=JiC4 - ArmSleeveFilletR", "in", "CALCULATED", "CHECK > 0: V4 pocket junction fits inside the arm curve"),
    ("ChkFrontFillet", "=FloorBotZ - SaddleFrontFilletR - SaddleAxisZ - 0.1 in", "in", "CALCULATED",
     "CHECK > 0: front fillet stays above the cylinder axis (0.1 in margin)"),
]

N_STRAIGHT = 9      # loft A: straight rear rim, RiseStartX -> arm tangent point (no rear flare)
N_ARC = 10          # loft B: arm arc, tangent point -> RiseEndAng (rear flare, trimmed at Y = 0)
N_STATIONS = N_STRAIGHT + N_ARC
STATION_COLS = [   # (alias prefix, expression template, unit)
    ("s", None, "in"),
    ("u", "=s%(i)d / Parameters.RiseLength", ""),
    ("arc", "=%(arc)d", ""),
    ("phi", "=arc%(i)d > 0 ? -90 deg + (s%(i)d - Parameters.RiseLenStraight) / Parameters.ArmRout * 180 deg / pi : -90 deg", "deg"),
    ("x", "=arc%(i)d > 0 ? Parameters.ArmCxL + Parameters.ArmRout * cos(phi%(i)d) : Parameters.RiseStartX + s%(i)d", "in"),
    ("y", "=arc%(i)d > 0 ? Parameters.ArmCy + Parameters.ArmRout * sin(phi%(i)d) : 0 in", "in"),
    ("t", "=Parameters.ArmThkL4Start + (Parameters.ArmThkL4 - Parameters.ArmThkL4Start) * (3 * u%(i)d ^ 2 - 2 * u%(i)d ^ 3)", "in"),
    ("z", "=s%(i)d <= Parameters.RiseSm ? Parameters.RiseR1 - sqrt(Parameters.RiseR1 ^ 2 - s%(i)d ^ 2) : "
          "Parameters.RiseHeight - Parameters.RiseR2 + sqrt(Parameters.RiseR2 ^ 2 - (Parameters.RiseLength - s%(i)d) ^ 2)", "in"),
    ("h", "=Parameters.RimHeight + z%(i)d", "in"),
]


def _station_s(i):
    if i < N_STRAIGHT:
        return "=Parameters.RiseLenStraight * %d / %d" % (i, N_STRAIGHT - 1)
    k = i - N_STRAIGHT
    return "=Parameters.RiseLenStraight + Parameters.RiseLenArc * %d / %d" % (k, N_ARC - 1)


def make_station_sheet(doc, group):
    st = doc.addObject("Spreadsheet::Sheet", "RiseStations")
    st.Label = "RiseStations"
    group.addObject(st)
    hdr = ["station"] + [c[0] for c in STATION_COLS]
    cols = "ABCDEFGHIJKLMNOP"
    for k, h in enumerate(hdr):
        st.set("%s1" % cols[k], h)
    for i in range(N_STATIONS):
        r = i + 2
        st.set("A%d" % r, str(i))
        for k, (pre, tmpl, unit) in enumerate(STATION_COLS):
            c = "%s%d" % (cols[k + 1], r)
            st.set(c, _station_s(i) if tmpl is None else tmpl % dict(i=i, arc=0 if i < N_STRAIGHT else 1))
            st.setAlias(c, "%s%d" % (pre, i))
            if unit == "in":
                st.setDisplayUnit(c, "in")
    doc.recompute()
    for i in range(N_STATIONS):
        for k in range(len(STATION_COLS)):
            c = "%s%d" % (cols[k + 1], i + 2)
            st.set(c, st.getContents(c))
    st.set("A%d" % (N_STATIONS + 3), "s: path length along the rear face; u: s / RiseLength; arc: 0 = loft A (straight rim), 1 = loft B (arm arc);")
    st.set("A%d" % (N_STATIONS + 4), "phi: arm angle; x,y: section origin on the rear face; t: thickness; z: crest Z; h: crest above floor top")
    doc.recompute()
    return st


def make_section_sketch(doc, group, i, rear_flare):
    """Closed section: floor flares (RimFilletR), flanks, full-round top (radius t/2).
    Sketch x = inward from the rear face, sketch y = up from the floor top.
    rear_flare=False (straight rim, the rear face is the shelf edge): the rear flank runs straight down."""
    import Sketcher
    import math as m
    V = App.Vector
    sk = doc.addObject("Sketcher::SketchObject", "RiseSection%02d" % i)
    group.addObject(sk)
    sk.MapMode = "Deactivated"
    st = doc.getObject("RiseStations")
    t = st.get("t%d" % i).Value; h = st.get("h%d" % i).Value
    sp = doc.getObject(SS)
    rf = sp.RimFilletR.Value; e = sp.Eps.Value
    C = Sketcher.Constraint
    A2 = Part.ArcOfCircle(Part.Circle(V(t / 2, h - t / 2, 0), V(0, 0, 1), t / 2), 0, m.pi)          # P5 -> P4
    L3 = Part.LineSegment(V(t, h - t / 2, 0), V(t, rf, 0))
    A3 = Part.ArcOfCircle(Part.Circle(V(t + rf, rf, 0), V(0, 0, 1), rf), m.pi, 1.5 * m.pi)          # P6 -> P7
    L4 = Part.LineSegment(V(t + rf, 0, 0), V(t + rf, -e, 0))
    if rear_flare:
        g = [Part.LineSegment(V(-rf, -e, 0), V(-rf, 0, 0)),                                            # 0
             Part.ArcOfCircle(Part.Circle(V(-rf, rf, 0), V(0, 0, 1), rf), 1.5 * m.pi, 2 * m.pi),       # 1 P2 -> P3
             Part.LineSegment(V(0, rf, 0), V(0, h - t / 2, 0)),                                        # 2
             A2, L3, A3, L4,                                                                           # 3 4 5 6
             Part.LineSegment(V(t + rf, -e, 0), V(-rf, -e, 0))]                                        # 7
        cs = [C("Coincident", 7, 2, 0, 1), C("Coincident", 0, 2, 1, 1),
              C("Tangent", 1, 2, 2, 1), C("Tangent", 2, 2, 3, 2), C("Tangent", 3, 1, 4, 1),
              C("Tangent", 4, 2, 5, 1), C("Coincident", 5, 2, 6, 1), C("Coincident", 6, 2, 7, 1),
              C("Vertical", 0), C("Vertical", 2), C("Vertical", 4), C("Vertical", 6), C("Horizontal", 7)]
        iA2, iA3 = 3, 5
        dims = [("DistanceX", 2, 1, "0 mm"), ("DistanceX", 1, 1, "-%s" % P("RimFilletR")),
                ("DistanceY", 1, 3, P("RimFilletR")), ("Radius", 1, None, P("RimFilletR")),
                ("DistanceY", 0, 1, "-%s" % P("Eps"))]
    else:
        g = [Part.LineSegment(V(0, -e, 0), V(0, h - t / 2, 0)),                                        # 0
             A2, L3, A3, L4,                                                                           # 1 2 3 4
             Part.LineSegment(V(t + rf, -e, 0), V(0, -e, 0))]                                          # 5
        cs = [C("Tangent", 0, 2, 1, 2), C("Tangent", 1, 1, 2, 1), C("Tangent", 2, 2, 3, 1),
              C("Coincident", 3, 2, 4, 1), C("Coincident", 4, 2, 5, 1), C("Coincident", 5, 2, 0, 1),
              C("Vertical", 0), C("Vertical", 2), C("Vertical", 4), C("Horizontal", 5)]
        iA2, iA3 = 1, 3
        dims = [("DistanceX", 0, 1, "0 mm"), ("DistanceY", 0, 1, "-%s" % P("Eps"))]
    dims += [("Radius", iA2, None, "RiseStations.t%d / 2" % i),
             ("DistanceY", iA2, 3, "RiseStations.h%d - RiseStations.t%d / 2" % (i, i)),
             ("Radius", iA3, None, P("RimFilletR")),
             ("DistanceY", iA3, 3, P("RimFilletR")),
             ("DistanceX", iA3, 2, "RiseStations.t%d + %s" % (i, P("RimFilletR")))]
    sk.addGeometry(g, False)
    for c in cs:
        sk.addConstraint(c)
    for typ, gi, pi, expr in dims:
        if typ == "Radius":
            k = sk.addConstraint(C("Radius", gi, sk.Geometry[gi].Radius))
        else:
            p = sk.getPoint(gi, pi)
            k = sk.addConstraint(C(typ, -1, 1, gi, pi, p.x if typ == "DistanceX" else p.y))
        sk.setExpression("Constraints[%d]" % k, expr)
    sk.setExpression(".Placement.Base.x", "RiseStations.x%d" % i)
    sk.setExpression(".Placement.Base.y", "RiseStations.y%d" % i)
    sk.setExpression(".Placement.Base.z", P("FloorTopZ"))
    sk.setExpression(".Placement.Rotation",
                     "rotation(vector(0; 0; 1); RiseStations.phi%d + 180 deg) * rotation(vector(1; 0; 0); 90 deg)" % i)
    return sk


class Bld4(Bld3):
    def top_round_at(self, n, x, y, rface, rb, material_inside, start, span, ztop):
        z0 = "%s - %s" % (ztop, rb)
        h = "%s + %s" % (rb, P("Eps"))
        if material_inside:
            band = self.ring(n + "_Band", x, y, "%s + %s" % (rface, P("Eps")), "%s - %s" % (rface, rb), z0, h, start, span)
            tc = "%s - %s" % (rface, rb)
        else:
            band = self.ring(n + "_Band", x, y, "%s + %s" % (rface, rb), "%s - %s" % (rface, P("Eps")), z0, h, start, span)
            tc = "%s + %s" % (rface, rb)
        tor = self.torus(n + "_Torus", tc, rb, x, y, z0, start, span)
        return self.cut(n, band, tor)


def add_parameters_v4(doc):
    s = doc.getObject(SS)
    if s.getCellFromAlias("RiseStartX"):
        raise RuntimeError("V4 parameters already present")
    # changed V3 cells
    rr = int(s.getCellFromAlias("SleeveTopZ")[1:])
    s.set("B%d" % rr, "=1.000 in"); s.set("D%d" % rr, "APPROVED")
    s.set("E%d" % rr, "Sleeve top Z (V4: extended 1.000 in above the rim top; V1-V3: 0)")
    r_eps = int(s.getCellFromAlias("Eps")[1:])
    r0 = r_eps - 1
    n = len(V4_PARAMS) + 1
    s.insertRows(str(r0), n)
    doc.recompute()
    for k, row in enumerate(V4_PARAMS):
        _set_row3(s, r0 + k, *row)
    for k, row in enumerate(V4_PARAMS):
        if row[1] is not None:
            s.set("B%d" % (r0 + k), s.getContents("B%d" % (r0 + k)))
    doc.recompute()
    rr = int(s.getCellFromAlias("SleeveTopEdgeR")[1:])
    s.set("B%d" % rr, "=ArmBullnoseRL4"); s.set("D%d" % rr, "CALCULATED")
    s.set("E%d" % rr, "Sleeve top OUTER edge round at Z = SleeveTopZ (V4: = left arm full-round radius)")
    doc.recompute()
    return s


def _insert_after(body, feat, target):
    body.insertObject(feat, target, True)
    return feat


def migrate_saddle_v4(doc):
    """Front-end fillet + unequal side fillets in Saddle_UpperBody."""
    up = doc.getObject("Saddle_UpperBody")
    E, Bg = P("Eps"), P("Big")
    ext, rmax = P("SaddleFrontExt"), P("SaddleFilletRmax")
    # floor patch covers the larger side fillet and the forward extension
    fp = doc.getObject("Saddle_FloorPatch")
    fp.setExpression("Length", "2 * (%s + 2 * %s)" % (P("SaddleRo0"), rmax))
    fp.setExpression("Width", "%s + %s + 2 * %s" % (P("SaddleLength"), ext, rmax))
    fp.setExpression(".Placement.Base.x", "%s - %s - 2 * %s" % (P("SaddleAxisX"), P("SaddleRo0"), rmax))
    # outer cone extended forward on the taper by SaddleFrontExt
    oc = doc.getObject("Saddle_OuterConeUpper")
    oc.setExpression("Radius1", "%s - %s * %s / 2" % (P("SaddleRo1"), P("TaperSlope"), ext))
    oc.setExpression("Height", "%s + %s" % (P("SaddleLength"), ext))
    oc.setExpression(".Placement.Base.y", "%s + %s" % (P("SaddleY1"), ext))
    for nm in ("Saddle_TrimTop", "Saddle_UpperCutBelowAxis"):
        o = doc.getObject(nm)
        o.setExpression("Width", "%s + 2 * %s + %s" % (P("SaddleLength"), Bg, ext))
        o.setExpression("Length", "2 * %s + 4 * %s + 2 * %s" % (P("SaddleRo0"), rmax, Bg))
        o.setExpression(".Placement.Base.x", "%s - %s - 2 * %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), rmax, Bg))
    doc.recompute()
    lowcut = doc.getObject("Saddle_UpperCutBelowAxis")
    zb = doc.getObject(SS).FloorBotZ.Value
    ax = doc.getObject(SS).SaddleAxisX.Value
    sh = lowcut.Shape
    jn = [(i, e) for i, e in enumerate(sh.Edges)
          if abs(e.BoundBox.ZMax - zb) < 1e-6 and abs(e.BoundBox.ZMin - zb) < 1e-6
          and e.Curve.__class__.__name__ not in ("Line", "Circle")]
    if len(jn) != 2:
        raise RuntimeError("saddle junction edges: found %d" % len(jn))
    right = ["Edge%d" % (i + 1) for i, e in jn if e.BoundBox.XMin > ax]
    left = ["Edge%d" % (i + 1) for i, e in jn if e.BoundBox.XMax < ax]
    ffil = doc.getObject("Saddle_FloorFillet")
    ffil.Base = (lowcut, right)
    ffil.Label = "Saddle_FloorFillet (RIGHT side, R = SaddleFloorFilletR)"
    doc.recompute()
    # left side fillet on the result of the right one (find the same edge again by geometry)
    sh2 = ffil.Shape
    le = [e for i, e in jn if e.BoundBox.XMax < ax][0]
    pm = le.valueAt(0.5 * (le.FirstParameter + le.LastParameter))
    cand = [(i, e) for i, e in enumerate(sh2.Edges)
            if e.Curve.__class__.__name__ not in ("Line", "Circle") and e.distToShape(Part.Vertex(pm))[0] < 1e-6
            and abs(e.BoundBox.ZMax - zb) < 1e-6]
    if len(cand) != 1:
        raise RuntimeError("left junction edge after right fillet: %d" % len(cand))
    fl = doc.addObject("PartDesign::Fillet", "Saddle_FloorFilletLeft")
    _insert_after(up, fl, ffil)
    fl.Base = (ffil, ["Edge%d" % (cand[0][0] + 1)])
    fl.setExpression("Radius", P("SaddleFloorFilletR_L"))
    fl.Refine = False
    fl.Label = "Saddle_FloorFilletLeft (R = SaddleFloorFilletR_L)"
    doc.recompute()
    # front fillet: keep only the YZ fillet profile in front of the saddle end face
    xl = "%s - %s - 2 * %s - %s" % (P("SaddleAxisX"), P("SaddleRo0"), rmax, Bg)
    L = "2 * %s + 4 * %s + 2 * %s" % (P("SaddleRo0"), rmax, Bg)
    zlo = "%s - %s - %s" % (P("SaddleAxisZ"), P("SaddleRo0"), Bg)
    rfr = P("SaddleFrontFilletR")
    y1 = P("SaddleY1")
    prev = fl
    feats = []
    def sub(typ, name):
        o = doc.addObject(typ, name)
        o.MapMode = "Deactivated"
        o.Refine = False
        return o
    a = sub("PartDesign::SubtractiveBox", "Saddle_FrontCutAhead")
    a.setExpression("Length", L); a.setExpression("Width", "%s + 2 * %s + %s" % (ext, rmax, Bg))
    a.setExpression("Height", "%s - (%s)" % (P("FloorBotZ"), zlo))
    a.setExpression(".Placement.Base.x", xl); a.setExpression(".Placement.Base.y", "%s + %s" % (y1, rfr))
    a.setExpression(".Placement.Base.z", zlo)
    b = sub("PartDesign::SubtractiveBox", "Saddle_FrontCutBelow")
    b.setExpression("Length", L); b.setExpression("Width", "%s + %s" % (rfr, E))
    b.setExpression("Height", "%s - %s - (%s)" % (P("FloorBotZ"), rfr, zlo))
    b.setExpression(".Placement.Base.x", xl); b.setExpression(".Placement.Base.y", y1)
    b.setExpression(".Placement.Base.z", zlo)
    d = sub("PartDesign::SubtractiveCylinder", "Saddle_FrontFilletTool")
    d.setExpression("Radius", rfr); d.setExpression("Height", L)
    d.Placement.Rotation = App.Rotation(App.Vector(0, 1, 0), 90)
    d.setExpression(".Placement.Base.x", xl)
    d.setExpression(".Placement.Base.y", "%s + %s" % (y1, rfr))
    d.setExpression(".Placement.Base.z", "%s - %s" % (P("FloorBotZ"), rfr))
    for o in (a, b, d):
        _insert_after(up, o, prev)
        prev = o
    # cylinder-envelope cutter extended further forward (same taper)
    ic = doc.getObject("Saddle_InnerConeUpper")
    ic.setExpression("Radius1", "%s - %s * %s / 2" % (P("SaddleRi1"), P("TaperSlope"), P("CavityFrontExt")))
    ic.setExpression("Height", "%s + %s + %s" % (P("SaddleLength"), Bg, P("CavityFrontExt")))
    ic.setExpression(".Placement.Base.y", "%s + %s" % (y1, P("CavityFrontExt")))
    doc.recompute()
    return dict(right=right, left=cand[0][0] + 1, order=[o.Name for o in up.Group], tip=up.Tip.Name)


def migrate_v4(doc):
    App.setActiveDocument(doc.Name)
    s = add_parameters_v4(doc)
    log = {}
    grp = doc.addObject("App::DocumentObjectGroup", "RisingLeftRim")
    grp.Label = "_11_RisingLeftRim_V4"
    b = Bld4(doc, grp)
    E = P("Eps"); zt = P("FloorTopZ")
    cx, cy = P("ArmCxL"), P("ArmCy")
    sx, sy = P("SleeveX"), P("SleeveY")
    H = P("SleeveTopZ")
    rj, rf, rb4 = P("ArmSleeveFilletR"), P("ArmFloorFilletR"), P("ArmBullnoseRL4")
    zw = "%s - %s" % (zt, E)
    hwall4 = "%s - (%s)" % (H, zw)

    # ---- 1. rising rim / arm loft --------------------------------------------
    st = make_station_sheet(doc, grp)
    secs = [make_section_sketch(doc, grp, i, rear_flare=(i >= N_STRAIGHT)) for i in range(N_STATIONS)]
    doc.recompute()
    loftA = b.add("Part::Loft", "LeftRise_LoftStraight")
    loftA.Sections = secs[:N_STRAIGHT]
    loftB = b.add("Part::Loft", "LeftRise_LoftArm")
    loftB.Sections = secs[N_STRAIGHT:]
    for lo in (loftA, loftB):
        lo.Solid = True; lo.Ruled = False; lo.Closed = False
    loftA.Label = "LeftRise_LoftStraight (sections 00-%02d, straight rear rim)" % (N_STRAIGHT - 1)
    loftB.Label = "LeftRise_LoftArm (sections %02d-%02d, arm arc)" % (N_STRAIGHT, N_STATIONS - 1)
    ytrim = b.box("LeftRise_TrimRear", "%s - %s + 2 * %s" % (sx, P("ArmCxL"), P("Big")),
                  "%s + %s" % (P("ShelfYc"), P("Big")), "%s - (%s) + 2 * %s" % (H, zt, P("Big")),
                  "%s - %s" % (P("ArmCxL"), P("Big")), "0 mm", "%s - %s" % (zt, P("Big")))
    loftT = b.common("LeftRise_ArmWall", [loftB, ytrim])
    loftT.Label = "LeftRise_ArmWall (arm loft trimmed at the rear edge Y = 0)"
    # ---- 2. junction zone: constant 0.200 in arm, webs, fillets at full height
    arm = b.ring("ArmL4_Band", cx, cy, P("ArmRout"), P("ArmRinL4"), zw, hwall4, P("RiseEndAng"),
                 "%s - %s" % (P("ArmPhiCS"), P("RiseEndAng")))
    wo_ann = b.ring("ArmL4_WebRear_Ann", cx, cy, "%s + %s" % (P("ArmRout"), rj), "%s - %s" % (P("ArmRout"), E), zw, hwall4)
    wi_ann = b.ring("ArmL4_WebPocket_Ann", cx, cy, "%s + %s" % (P("ArmRinL4"), E), "%s - %s" % (P("ArmRinL4"), rj), zw, hwall4)
    webs = []
    for tag, ann, jx, jy, stt, sp in (("Rear", wo_ann, "JoX", "JoY", "JoStart", "JoSpan"),
                                       ("Pocket", wi_ann, "JiX4", "JiY4", "JiStart4", "JiSpan4")):
        dS = b.cyl("ArmL4_Web%s_DiskS" % tag, P("JS"), hwall4, sx, sy, zw)
        fan = b.cyl("ArmL4_Web%s_Fan" % tag, P("JS"), hwall4, P(jx), P(jy), zw, P(stt), P(sp))
        com0 = b.common("ArmL4_Web%s_AnnDisk" % tag, [ann, dS])
        com = b.common("ArmL4_Web%s_Region" % tag, [com0, fan])
        dJ = b.cyl("ArmL4_Web%s_DiskJ" % tag, rj, "%s + 2 * %s" % (hwall4, E), P(jx), P(jy), "%s - %s" % (zw, E))
        webs.append(b.cut("ArmL4_Web%s" % tag, com, dJ))
    f_pocket = b.floor_fillet("ArmL4_FloorFilletPocket", cx, cy, P("ArmRinL4"), rf, False, P("RiseEndAng"),
                              "%s - %s" % (P("JiAng4"), P("RiseEndAng")))
    f_rear = b.floor_fillet("ArmL4_FloorFilletRear", cx, cy, P("ArmRout"), rf, True, P("RiseEndAng"),
                            "%s - %s" % (P("JoAng"), P("RiseEndAng")))
    f_wo = b.floor_fillet("ArmL4_WebRear_FloorFillet", P("JoX"), P("JoY"), rj, rf, False, P("JoStart"), P("JoSpan"))
    f_wi = b.floor_fillet("ArmL4_WebPocket_FloorFillet", P("JiX4"), P("JiY4"), rj, rf, False, P("JiStart4"), P("JiSpan4"))
    addL4 = b.fuse("ArmL4_Additive", [arm] + webs + [f_pocket, f_rear, f_wo, f_wi])
    addL4.Refine = True
    # top rounds at Z = SleeveTopZ
    t_rear = b.top_round_at("ArmL4_TopRoundRear", cx, cy, P("ArmRout"), rb4, True, P("RiseEndAng"),
                            "%s - %s" % (P("JoAng"), P("RiseEndAng")), H)
    t_pock = b.top_round_at("ArmL4_TopRoundPocket", cx, cy, P("ArmRinL4"), rb4, False, P("RiseEndAng"),
                            "%s - %s" % (P("JiAng4"), P("RiseEndAng")), H)
    t_wo = b.top_round_at("ArmL4_WebRear_TopRound", P("JoX"), P("JoY"), rj, rb4, False, P("JoStart"), P("JoSpan"), H)
    t_wi = b.top_round_at("ArmL4_WebPocket_TopRound", P("JiX4"), P("JiY4"), rj, rb4, False, P("JiStart4"), P("JiSpan4"), H)
    topL4 = b.fuse("ArmL4_TopRounds", [t_rear, t_pock, t_wo, t_wi])
    # ---- 3. remove the V3 left rear rim between RiseStartX and the arm tangent point
    rimcut = b.box("LeftRise_RimCutter", "%s - %s" % (cx, P("RiseStartX")), "%s + %s" % (P("OpenCutY"), P("Big")),
                   "%s - %s" % (P("Big"), P("OpeningZ")), P("RiseStartX"), "-%s" % P("Big"), P("OpeningZ"))
    # ---- 4. sleeve top round moved to the new top, one arc (all but the left arm entry)
    for nm, zexpr in (("SleeveTop_RoundRear_Band_Out", "%s - %s" % (H, P("SleeveTopEdgeR"))),
                      ("SleeveTop_RoundRear_Band_In", "%s - %s - %s" % (H, P("SleeveTopEdgeR"), E)),
                      ("SleeveTop_RoundRear_Torus", "%s - %s" % (H, P("SleeveTopEdgeR")))):
        doc.getObject(nm).setExpression(".Placement.Base.z", zexpr)
    bo = doc.getObject("SleeveTop_RoundRear_Band_Out")
    bo.setExpression("Angle", P("SlvRoundSpan4"))
    to = doc.getObject("SleeveTop_RoundRear_Torus")
    to.setExpression("Angle3", "%s + 2 * %s" % (P("SlvRoundSpan4"), P("ArmAngMargin")))
    doc.getObject("SleeveTop_RoundRear").Label = "SleeveTop_Round (V4: at SleeveTopZ, all round except left arm entry)"
    # right-arm top-round cutters (Z = 0): keep them out of the now taller sleeve wall
    clip = b.cyl("ArmR_TopRounds_SleeveClip", P("SleeveOR"), "%s - %s + 2 * %s" % (H, P("FloorBotZ"), P("Big")),
                 sx, sy, "%s - %s" % (P("FloorBotZ"), P("Big")))
    topR_c = b.cut("ArmR_TopRounds_Clipped", doc.getObject("ArmR_TopRounds"), clip)
    tops = doc.getObject("V3_TopRounds_Tool")
    tops.Shapes = [topR_c, doc.getObject("SleeveTop_RoundRear"), topL4]
    tops.Label = "TopRounds_Tool (V4)"
    # ---- 5. re-wire the final chain --------------------------------------------
    gf = _group3(doc, "FinalManufacturingSolid")
    f03a = doc.getObject("Fin_03a_CutRearOpening")
    f03b = doc.getObject("Fin_03b_AddArms")
    f04 = doc.getObject("Fin_04_CutSleeveBore")
    c_rim = b.cut("Fin_03a2_CutLeftRiseRim", f03a, rimcut)
    f03b.Shapes = [c_rim, doc.getObject("ArmR_Additive")]
    f03b.Label = "Fin_03b_AddArms (V4: right arm only)"
    wallL = b.fuse("LeftRise_Assembly", [loftA, loftT, addL4])
    wallL.Label = "LeftRise_Assembly (rising rim + left arm, fused first: more robust than one multi-fuse)"
    a_left = b.fuse("Fin_03c_AddRisingLeftRimAndArm", [f03b, wallL])
    a_left.Refine = False      # (refine here merged loft faces into invalid B-spline patches)
    f04.Base = a_left
    # the rim bullnose cutters must not touch the rising rim: extend their trim box to RiseStartX
    tb = doc.getObject("RearOpening_BullnoseTrim")
    tb.setExpression("Length", "%s - %s" % (P("ArmCxR"), P("RiseStartX")))
    tb.setExpression(".Placement.Base.x", P("RiseStartX"))
    tb.Label = "RearOpening_BullnoseTrim (V4: RiseStartX .. right arm tangent point)"
    for o in (c_rim, a_left):
        grp.removeObject(o); gf.addObject(o)
    # final solid: V1-V3 used Part::Refine.  Refining V4 merges the sleeve OD faces split by the
    # clipped right-arm round cutters into a face with invalid p-curves (BOP check fails), so the
    # V4 'ShelfSolid' is a pass-through PartDesign body on the last boolean (no refine).
    old = doc.getObject("ShelfSolid")
    src = old.Source
    doc.removeObject("ShelfSolid")
    body = doc.addObject("PartDesign::Body", "ShelfSolid")
    gf.addObject(body)
    body.BaseFeature = src
    body.Label = "ShelfSolid_Manufacturing"
    doc.recompute()
    for o in body.Group:
        if hasattr(o, "Refine"):
            o.Refine = False
    if App.GuiUp:
        body.ViewObject.ShapeColor = (0.85, 0.85, 0.80)
        body.ViewObject.Visibility = True
    doc.recompute()
    # ---- 6. saddle ------------------------------------------------------------------
    log["saddle"] = migrate_saddle_v4(doc)
    for o in b.new:
        if o not in (c_rim, a_left):
            o.Visibility = False
    for o in secs:
        o.Visibility = False
    doc.recompute()
    notes = doc.getObject("ModelNotes")
    if notes is not None and hasattr(notes, "Text"):
        notes.Text = notes.Text + V4_NOTES
    return log


V4_NOTES = """

PHASE 3 (V4) CHANGES
 * SleeveTopZ = +1.000 in (sleeve OD/ID/centre/below-shelf engagement unchanged).
   Sleeve top outer edge round SleeveTopEdgeR (= ArmBullnoseRL4) at the new top,
   all round except the left arm entry (right arm now joins the sleeve wall at Z = 0).
 * _11_RisingLeftRim_V4: two Part::Lofts through parametric section sketches
   (sheet RiseStations): LeftRise_LoftStraight (RiseSection00-05, straight rear rim,
   rear flank = shelf edge) and LeftRise_LoftArm (RiseSection06-13, arm arc, with
   rear floor flare; trimmed at Y = 0).  Section i sits on the rear face at path
   position s_i,
   normal to the path; crest height = reverse-curve S (RiseStartX, RiseEndAng,
   RiseHeight, RiseShape), thickness = smoothstep RimThk -> ArmThkL4.  Full-round
   top, RimFilletR floor flares; trimmed at Y = 0.  The V3 rear rim between
   RiseStartX and ArmCxL is removed (Fin_03a2) and replaced by the lofts.
 * Junction zone (RiseEndAng .. sleeve): ArmL4_* constant-thickness arm (0.200 in),
   rebuilt junction webs (ArmSleeveFilletR), floor fillets, top rounds at Z = SleeveTopZ.
 * V3 ArmL_* objects are kept only as the mirror source of the (unchanged) right arm.
 * Saddle_UpperBody: right side fillet SaddleFloorFilletR, left side
   SaddleFloorFilletR_L; outer cone extended SaddleFrontExt; Saddle_FrontCut* +
   Saddle_FrontFilletTool leave a SaddleFrontFilletR fillet between the front end face
   and the floor underside; Saddle_InnerConeUpper extended CavityFrontExt on the taper
   so nothing protrudes into the cylinder envelope.
 * Chain: ... Fin_03a -> Fin_03a2 -> Fin_03b (right arm) -> Fin_03c (+ rising left
   rim + left arm) -> Fin_04 (bore) -> Fin_05/06 (rim bullnose, trimmed from RiseStartX
   to the right arm) -> Fin_06a (top rounds) -> Fin_07.. -> ShelfSolid.
 * Right-arm top-round cutters (Z = 0) are clipped by the sleeve OD so they do not
   groove the taller sleeve.
 * ShelfSolid is now a PartDesign::Body whose BaseFeature is Fin_09 (no Part::Refine:
   refining merged the clipped sleeve OD faces into a face that fails the BOP check).
 * Keep all Chk* cells positive.
"""


def build_v4(doc_name="ShowerShelf_3Bottle_V4"):
    """Build V1 from scratch, apply the Phase 1B, 1C and Phase 3 migrations."""
    doc = build(doc_name)
    migrate(doc); doc.recompute()
    migrate_v3(doc); doc.recompute()
    migrate_v4(doc); doc.recompute()
    return doc


if __name__ == "__main__":
    build_v4()


def save_and_journal(doc, path):
    """Explicitly save a built model and record immutable evidence when enabled."""
    import os

    doc.saveAs(path)
    if os.environ.get("FREECAD_JOURNAL_PROJECT"):
        _journal_bridge().record_cad(doc, path, __file__, getattr(doc, "Name", None))
    return path

# Optional engineering journal bridge; set FREECAD_JOURNAL_PROJECT to enable.
def _journal_bridge():
    import os, sys
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    import journal_integration
    return journal_integration
