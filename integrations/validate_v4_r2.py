# -*- coding: utf-8 -*-
"""Geometry validation for ShowerShelf_3Bottle_V4 (Phase 3).  validate(doc, out_dir) -> dict"""
import math, os, json, time
import FreeCAD as App
import Part

IN = 25.4
V = App.Vector

_boolean_retry_count = 0


def _p(s, a):
    v = s.get(a)
    return float(v.Value) if hasattr(v, "Value") else float(v)


def _chord(solid, p0, p1):
    """Length of material along the segment p0-p1 and the material intervals (params 0..1)."""
    e = Part.LineSegment(p0, p1).toShape()
    global _boolean_retry_count
    for attempt in range(3):
        try:
            c = solid.common(e)
            break
        except ValueError as exc:
            if str(exc) != "Null shape" or attempt == 2:
                raise
            _boolean_retry_count += 1
    L = (p1 - p0).Length
    segs = []
    for ed in c.Edges:
        a = (ed.Vertexes[0].Point - p0).Length / L
        b = (ed.Vertexes[-1].Point - p0).Length / L
        segs.append(tuple(sorted((a, b))))
    return sum(x.Length for x in c.Edges), sorted(segs)


def validate(doc, out_dir=None, export_basename=None):
    global _boolean_retry_count
    _boolean_retry_count = 0
    t0 = time.time()
    s = doc.getObject("Parameters")
    g = lambda a: _p(s, a)
    R = {}
    doc.recompute()
    bad = [o.Name for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
    sh = doc.getObject("ShelfSolid").Shape
    try:
        sh.check(True); bop = "pass"
    except Exception as ex:
        bop = "FAIL: " + str(ex)[:300]
    R["solid"] = dict(objects_in_error=bad, n_solids=len(sh.Solids), valid=sh.isValid(), bop_check=bop,
                      max_tolerance_mm=sh.getTolerance(1), volume_mm3=round(sh.Volume, 1),
                      volume_in3=round(sh.Volume / IN ** 3, 4), mass_PA12_g=round(sh.Volume * 1.01e-3, 1),
                      faces=len(sh.Faces), smallest_face_mm2=round(min(f.Area for f in sh.Faces), 3),
                      bbox_in=[round(x / IN, 4) for x in (sh.BoundBox.XMin, sh.BoundBox.XMax, sh.BoundBox.YMin,
                                                           sh.BoundBox.YMax, sh.BoundBox.ZMin, sh.BoundBox.ZMax)])
    chk = {}
    for r in range(2, 400):
        a = s.getAlias("B%d" % r)
        if a and a.startswith("Chk"):
            chk[a] = round(g(a) / (IN if "deg" not in str(s.get(a)) else 1), 5)
    R["check_cells(in or deg)"] = chk
    R["rising_rim_features"] = {n: dict(valid=doc.getObject(n).Shape.isValid(), volume_mm3=round(doc.getObject(n).Shape.Volume, 1))
                                for n in ("LeftRise_LoftStraight", "LeftRise_LoftArm", "LeftRise_ArmWall", "ArmL4_Additive", "LeftRise_Assembly")}
    R["rising_rim_features_ok"] = all(x["valid"] and x["volume_mm3"] > 0 for x in R["rising_rim_features"].values())
    R["check_cells_all_positive"] = all(v >= 0 for v in chk.values())
    # ---- sleeve
    sx, sy, IR, OR = g("SleeveX"), g("SleeveY"), g("SleeveIR"), g("SleeveOR")
    ztop, zt, zb, az = g("SleeveTopZ"), g("FloorTopZ"), g("FloorBotZ"), g("SaddleAxisZ")
    probe = Part.makeCylinder(IR - 0.01, ztop - az + 50, V(sx, sy, az - 20))
    R["sleeve"] = dict(top_Z_in=round(ztop / IN, 4), bore_dia_in=round(2 * IR / IN, 4), od_in=round(2 * OR / IN, 4),
                       wall_in=round((OR - IR) / IN, 4), centre_in=[round(sx / IN, 4), round(sy / IN, 4)],
                       solid_top_Z_in=round(sh.BoundBox.ZMax / IN, 4),
                       material_inside_bore_mm3=round(probe.common(sh).Volume, 4))
    bore_faces = [f for f in sh.Faces if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Radius - IR) < 1e-4]
    R["sleeve"]["bore_face_Z_range_in"] = [round(min(f.BoundBox.ZMin for f in bore_faces) / IN, 4),
                                           round(max(f.BoundBox.ZMax for f in bore_faces) / IN, 4)]
    # ---- bottle clearances (cylinders above the floor fillets)
    bR = g("BottleR"); by = g("BottleY"); z0 = zt + g("SleeveFilletR") + 0.01 * IN     # above all wall-to-floor fillets
    clr = {}
    for k in (1, 2, 3):
        cyl = Part.makeCylinder(bR, 8 * IN, V(g("Bottle%dX" % k), by, z0))
        above = sh.common(Part.makeBox(30 * IN, 10 * IN, 10 * IN, V(-15 * IN, -5 * IN, z0 - 0.01)))   # walls only (no floor)
        d = cyl.distToShape(above)
        clr["bottle%d" % k] = dict(min_clearance_in=round(d[0] / IN, 4),
                                   nearest_point_on_shelf_in=[round(c / IN, 3) for c in d[1][0][1]])
    wall = doc.getObject("LeftRise_Assembly").Shape
    clr["bottle2_to_rising_left_rim_and_arm_in"] = round(Part.makeCylinder(bR, 8 * IN, V(g("Bottle2X"), by, z0)).distToShape(wall)[0] / IN, 4)
    clr["bottle3_to_rising_left_rim_in"] = round(Part.makeCylinder(bR, 8 * IN, V(g("Bottle3X"), by, z0)).distToShape(wall)[0] / IN, 4)
    clr["required_in"] = dict(rim=g("ClrBottleRim") / IN, sleeve=g("ClrBottleSleeve") / IN)
    R["bottle_clearance"] = clr
    # ---- drainage
    hw, hc = g("DrainSlotHalfW"), g("DrainSlotHalfC")
    dr = {}
    for tag, x in (("left", g("DrainSlotLeftX")), ("right", g("DrainSlotRightX"))):
        pr = Part.makeBox(2 * hc, 2 * hw - 0.2, 60, V(x - hc, g("DrainSlotY") - hw + 0.1, zb - 20))
        dr["slot_%s_material_mm3" % tag] = round(pr.common(sh).Volume, 4)
    xo = g("ArmHalfOpen") - 0.7 * IN
    ob = Part.makeBox(2 * xo, 0.06 * IN, ztop - zt + 5, V(sx - xo, 0.0, zt + 0.02))
    dr["rear_opening_material_above_sill_mm3"] = round(ob.common(sh).Volume, 4)
    dr["rear_opening_sill_Z_in"] = round(zt / IN, 4)
    dr["rear_opening_width_in(param)"] = round(g("DrainOpeningWidth") / IN, 4)
    dr["floor_present_under_opening"] = sh.isInside(V(sx, 0.05 * IN, zt - 0.02), 1e-4, True)
    R["drainage"] = dr
    # ---- floor thickness (vertical probes on a grid, excluding slots/saddle/sleeve)
    th = []
    xmin, xmax = g("ShelfXmin"), g("ShelfXmax")
    for i in range(1, 40):
        x = xmin + (xmax - xmin) * i / 40
        for y in (0.35 * IN, 1.0 * IN, 1.79 * IN, 2.6 * IN, 3.25 * IN):
            if abs(x - sx) < 1.3 * IN and y < g("SaddleY1") + 0.4 * IN:
                continue
            if math.hypot(x - sx, y - sy) < OR + 0.2 * IN:
                continue
            if any(abs(x - xs) < hc + hw + 1 and abs(y - g("DrainSlotY")) < hw + 1 for xs in (g("DrainSlotLeftX"), g("DrainSlotRightX"))):
                continue
            L, segs = _chord(sh, V(x, y, zb - 5), V(x, y, zt - 0.001))
            if L > 0:
                th.append(L)
    R["floor"] = dict(min_thickness_in=round((min(th) + 0.001) / IN, 4), samples=len(th), required_in=round(g("FloorThk") / IN, 4))
    # ---- saddle taper and wrap (inner mating surface)
    ax = g("SaddleAxisX"); Ri0 = g("SaddleRi0"); slope = g("TaperSlope"); y0, y1 = g("SaddleY0"), g("SaddleY1")
    dev, angs = [], []
    for f in sh.Faces:
        if f.BoundBox.ZMax > zb + 0.01 or f.BoundBox.YMax > y1 + 0.5:
            continue
        u0, u1, v0, v1 = f.ParameterRange
        for a in (0.1, 0.3, 0.5, 0.7, 0.9):
            for b in (0.1, 0.3, 0.5, 0.7, 0.9):
                p = f.valueAt(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b)
                if not f.isInside(p, 1e-3, True):
                    continue
                ri = Ri0 - slope / 2 * (p.y - y0)
                d = math.hypot(p.x - ax, p.z - az) - ri
                if abs(d) < 0.02:
                    dev.append(abs(d)); angs.append(math.degrees(math.atan2(p.x - ax, p.z - az)))
    R["saddle"] = dict(inner_surface_max_dev_from_taper_mm=round(max(dev), 5), samples=len(dev),
                       inner_surface_angle_range_deg=[round(min(angs), 2), round(max(angs), 2)],
                       wrap_measured_on_cone_deg=round(max(angs) - min(angs), 2),
                       wrap_param_deg=g("SaddleWrap"), lip_edge_fillet_in=round(g("SaddleEdgeR") / IN, 4),
                       radial_clearance_in=round(g("SaddleClr") / IN, 4),
                       taper_dia_per_in=round(slope, 6),
                       side_fillet_left_in=round(g("SaddleFloorFilletR_L") / IN, 4),
                       side_fillet_right_in=round(g("SaddleFloorFilletR") / IN, 4),
                       front_fillet_in=round(g("SaddleFrontFilletR") / IN, 4))
    for n in ("Saddle_UpperBody", "Saddle_FloorFillet", "Saddle_FloorFilletLeft", "Saddle_FrontFilletTool", "Saddle_LowerBody"):
        o = doc.getObject(n)
        R["saddle"]["feature_%s" % n] = "ok" if (o and o.Shape.isValid() and "Invalid" not in o.State) else "INVALID"
    # ---- mount interference (nominal cylinder on the taper, extended forward; vertical tube)
    rr = lambda y: g("DesignDiaRear") / 2 - slope / 2 * (y - y0)
    ya, yb = -0.4 * IN, y1 + 1.0 * IN
    cone = Part.makeCone(rr(ya), rr(yb), yb - ya, V(ax, ya, az), V(0, 1, 0))
    ztc = az + rr(sy)
    tube = Part.makeCylinder(g("TubeOD") / 2, 12 * IN - ztc, V(sx, sy, ztc + 0.2))
    R["mount"] = dict(cylinder_overlap_mm3=round(cone.common(sh).Volume, 5), cylinder_min_gap_in=round(cone.distToShape(sh)[0] / IN, 5),
                      tube_overlap_mm3=round(tube.common(sh).Volume, 5), tube_min_gap_in=round(tube.distToShape(sh)[0] / IN, 5),
                      note="cylinder = nominal design diameter on the measured taper, extended %.2f in past the saddle front end" % 1.0)
    # ---- rising rim: crest height and thickness along the rear-face path
    X0, Ls, La, L = g("RiseStartX"), g("RiseLenStraight"), g("RiseLenArc"), g("RiseLength")
    Cx, Cy, Rout = g("ArmCxL"), g("ArmCy"), g("ArmRout")
    R1, R2, Sm, Hr = g("RiseR1"), g("RiseR2"), g("RiseSm"), g("RiseHeight")
    th0, th1 = g("ArmThkL4Start"), g("ArmThkL4")
    prof = []
    for i in range(0, 61):
        sv = L * i / 60
        if sv <= Ls:
            o = V(X0 + sv, 0, 0); n = V(0, 1, 0)
        else:
            ph = -math.pi / 2 + (sv - Ls) / Rout
            o = V(Cx + Rout * math.cos(ph), Cy + Rout * math.sin(ph), 0); n = V(-math.cos(ph), -math.sin(ph), 0)
        u = sv / L
        t_des = th0 + (th1 - th0) * (3 * u * u - 2 * u ** 3)
        z_des = R1 - math.sqrt(max(R1 * R1 - sv * sv, 0)) if sv <= Sm else Hr - R2 + math.sqrt(max(R2 * R2 - (L - sv) ** 2, 0))
        c = o + n * (t_des / 2)
        Lz, segz = _chord(sh, V(c.x, c.y, zt + 1), V(c.x, c.y, Hr + 10))
        crest = zt + 1 + segz[0][1] * (Hr + 10 - zt - 1) if segz else float("nan")
        zm = zt + 0.25 * IN
        p0 = o - n * 1.0; p1 = o + n * 12.0
        Lt, segt = _chord(sh, V(p0.x, p0.y, zm), V(p1.x, p1.y, zm))
        thick = (segt[0][1] - segt[0][0]) * 13.0 if segt else float("nan")
        prof.append(dict(s_in=round(sv / IN, 4), crest_Z_in=round(crest / IN, 4), crest_design_in=round(z_des / IN, 4),
                         thickness_in=round(thick / IN, 4), thickness_design_in=round(t_des / IN, 4)))
    cz = [p["crest_Z_in"] for p in prof]; tz = [p["thickness_in"] for p in prof]
    ds = L / 60 / IN
    slope_ = [(cz[i + 1] - cz[i]) / ds for i in range(len(cz) - 1)]
    R["rising_rim"] = dict(
        crest_max_dev_from_design_in=round(max(abs(p["crest_Z_in"] - p["crest_design_in"]) for p in prof), 5),
        crest_start_end_in=[cz[0], cz[-1]], crest_monotonic=all(slope_[i] >= -1e-4 for i in range(len(slope_))),
        max_crest_slope_deg=round(math.degrees(math.atan(max(slope_))), 2),
        max_slope_change_per_step_deg=round(max(abs(math.degrees(math.atan(slope_[i + 1]) - math.atan(slope_[i])))
                                                for i in range(len(slope_) - 1)), 3),
        thickness_start_end_in=[tz[0], tz[-1]], thickness_monotonic=all(tz[i + 1] >= tz[i] - 2e-4 for i in range(len(tz) - 1)),
        thickness_max_dev_from_design_in=round(max(abs(p["thickness_in"] - p["thickness_design_in"]) for p in prof), 5),
        profile=prof)
    # ---- exports
    if out_dir and export_basename:
        import Mesh, MeshPart, Import
        stp = os.path.join(out_dir, export_basename + ".step")
        stl = os.path.join(out_dir, export_basename + ".stl")
        Import.export([doc.getObject("ShelfSolid")], stp)
        re_ = Part.read(stp)
        try:
            re_.check(True); rbop = "pass"
        except Exception as ex:
            rbop = "FAIL: " + str(ex)[:200]
        m = MeshPart.meshFromShape(Shape=sh, LinearDeflection=0.127, AngularDeflection=math.radians(10), Relative=False)
        m.write(stl)
        mr = Mesh.Mesh(stl)
        R["exports"] = dict(step=dict(file=os.path.basename(stp), bytes=os.path.getsize(stp), solids=len(re_.Solids),
                                      valid=re_.isValid(), bop_check=rbop, volume_rel_diff=(re_.Volume - sh.Volume) / sh.Volume),
                            stl=dict(file=os.path.basename(stl), bytes=os.path.getsize(stl), facets=mr.CountFacets,
                                     solid_closed=mr.isSolid(), non_manifold=mr.hasNonManifolds(), self_intersect=mr.hasSelfIntersections(),
                                     volume_rel_diff=(mr.Volume - sh.Volume) / sh.Volume))
    R["elapsed_s"] = round(time.time() - t0, 1)
    R["boolean_retries"] = _boolean_retry_count
    return R


if __name__ == "__main__":
    import sys
    d = App.openDocument(sys.argv[-1])
    print(json.dumps(validate(d), indent=1, default=str))


def validate_and_journal(doc, out_dir=None, export_basename=None, report_path=None):
    """Validate and, when enabled, journal against verified saved CAD evidence.

    A document with unsaved changes is rejected. Re-checking the document and
    file hash after validation prevents recording results for a replaced model.
    Plain validate(doc) remains available without journaling.
    """
    journaling = bool(os.environ.get("FREECAD_JOURNAL_PROJECT"))
    if journaling:
        if not report_path:
            raise ValueError("report_path is required when journaling validation")
        bridge = _journal_bridge()
        model_path, model_digest = bridge.verify_saved_model(doc)
        if os.path.abspath(report_path) == os.path.abspath(model_path):
            raise ValueError("Validation report must not overwrite the FreeCAD model")
    result = validate(doc, out_dir, export_basename)
    if journaling:
        bridge.verify_saved_model(doc, model_digest, expected_path=model_path)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        bridge.record_validation(result, model_path, report_path)
    return result


# Optional engineering journal bridge; set FREECAD_JOURNAL_PROJECT to enable.
def _journal_bridge():
    import os, sys
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    import journal_integration
    return journal_integration
