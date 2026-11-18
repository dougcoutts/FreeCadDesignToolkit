# -*- coding: utf-8 -*-
"""
ShowerShelf_FEM_Screening.py -- reproducible fixed-mount FEM screening for the
ShowerShelf_3Bottle design iterations (Phase 3).

One configuration file drives everything: model files, material, loads, mesh,
boundary conditions, result regions, plots.  For each model in the config the
script

    1. opens the manufacturing FCStd (read only; never saved) and copies ShelfSolid
    2. reads the dimensions it needs from the 'Parameters' spreadsheet
    3. imprints the bottle-base contact rings (load footprints) on the floor top
    4. meshes with Gmsh (10-node tets, box + curvature refinement)
    5. writes a CalculiX deck: PA12 linear elastic, gravity, bottle weights and
       pump load as uniform pressure on the rings, fixed saddle + bore (idealised)
    6. runs CalculiX
    7. extracts displacements, stresses, reactions and region results
    8. writes <tag>_summary.json, <tag>_surface.npz and contour plots
and finally writes a comparison report (markdown + plots) across all models.

Units in the solver files: mm, N, MPa, tonne (t/mm^3), s.

Run
  * from the FreeCAD Python console / macro:
        import ShowerShelf_FEM_Screening as S;  S.main(r"...\\FEM_Screening_config.json")
  * unattended (no GUI):
        set SHELF_FEM_CONFIG=...\\FEM_Screening_config.json
        "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" ShowerShelf_FEM_Screening.py
    (optional: set SHELF_FEM_ONLY=V4,V4_boreV3 to run a subset; SHELF_FEM_REPORT_ONLY=1
     to rebuild the comparison from existing results)

The screening model is IDEALISED: the saddle inner surface and the sleeve bore are
fully fixed.  It ranks design variants; it does not predict installed behaviour
(mount clearances, separation and rocking are not represented).
"""
import os, sys, json, math, time, re, hashlib, subprocess, shutil, platform

import numpy as np

IN = 25.4
G_MM = 9810.0
SCRIPT_VERSION = "1.0 (Phase 3, 2026-11-16)"

GMSH2CCX_TET10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]
CCX_TET_FACES = {1: (0, 1, 2), 2: (0, 3, 1), 3: (1, 3, 2), 4: (2, 3, 0)}

PARAM_KEYS = ("SleeveX", "SleeveY", "SleeveIR", "SleeveOR", "SleeveTopZ", "SaddleAxisX", "SaddleAxisZ",
              "SaddleY0", "SaddleY1", "SaddleRi0", "TaperSlope", "FloorTopZ", "FloorBotZ", "BottleY",
              "Bottle1X", "Bottle2X", "Bottle3X", "BottleR", "ShelfXmin", "ShelfXmax", "ShelfYc",
              "ShelfDepth", "RimThk")


# ============================================================ utilities
def log(msg, fh=None):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if fh is not None:
        fh.write(line + "\n"); fh.flush()


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def tool_version(exe, args):
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=60)
        t = (r.stdout + r.stderr).strip()
        m = re.search(r"Version\s+([\d.]+)", t) or re.search(r"([\d]+\.[\d]+\.[\d]+)", t)
        return m.group(1) if m else t[:40]
    except Exception as e:   # pragma: no cover
        return "unknown (%s)" % e


# ============================================================ geometry
def load_model(fcstd):
    """Copy ShelfSolid + parameters from an FCStd without modifying it."""
    import FreeCAD as App
    path = os.path.abspath(fcstd)
    opened_here = False
    doc = None
    for d in App.listDocuments().values():
        if os.path.abspath(d.FileName or "") == path:
            doc = d
    if doc is None:
        try:
            doc = App.openDocument(path, hidden=True)
        except TypeError:
            doc = App.openDocument(path)
        opened_here = True
    try:
        s = doc.getObject("Parameters")
        P = {}
        for k in PARAM_KEYS:
            v = s.get(k)
            P[k] = float(v.Value) if hasattr(v, "Value") else float(v)
        shelf = doc.getObject("ShelfSolid").Shape.copy()
        info = dict(document=doc.Name, label=doc.Label, sha256_16=sha16(path), file=path,
                    volume_mm3=shelf.Volume, valid=shelf.isValid(), solids=len(shelf.Solids))
    finally:
        if opened_here:
            App.closeDocument(doc.Name)
    return shelf, P, info


def imprint_rings(shelf, P, L):
    import FreeCAD as App, Part
    zt = P["FloorTopZ"]
    ro, ri = L["ring_od_in"] * IN / 2, L["ring_id_in"] * IN / 2
    tools = []
    for k in (1, 2, 3):
        c = App.Vector(P["Bottle%dX" % k], P["BottleY"], zt)
        ring = Part.Face(Part.Wire(Part.makeCircle(ro, c))).cut(Part.Face(Part.Wire(Part.makeCircle(ri, c)))).Faces[0]
        if k == L["pump_bottle"]:     # front / rear halves (off-centre option)
            hb = Part.makePlane(4 * ro, 2 * ro, App.Vector(c.x - 2 * ro, c.y, zt))
            tools += [ring.common(hb), ring.cut(hb)]
        else:
            tools.append(ring)
    gf = shelf.generalFuse(tools)[0]
    sol = list(gf.Solids)
    if len(sol) != 1:
        raise RuntimeError("imprint produced %d solids" % len(sol))
    if abs(sol[0].Volume - shelf.Volume) > 1e-4 * shelf.Volume:
        raise RuntimeError("imprint changed the volume")
    return sol[0]


def classify_faces(shelf, P, L):
    zt = P["FloorTopZ"]
    groups = {k: [] for k in ("SH_SADDLE", "SH_BORE", "RING1", "RING2", "RINGPF", "RINGPR")}
    ro, ri = L["ring_od_in"] * IN / 2, L["ring_id_in"] * IN / 2
    ax, az0 = P["SaddleAxisX"], P["SaddleAxisZ"]
    ri_y = lambda y: P["SaddleRi0"] - P["TaperSlope"] / 2 * (y - P["SaddleY0"])
    others = [k for k in (1, 2, 3) if k != L["pump_bottle"]]
    for i, f in enumerate(shelf.Faces):
        u0, u1, v0, v1 = f.ParameterRange
        pts = [f.valueAt(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b) for a in (0.2, 0.5, 0.8) for b in (0.2, 0.5, 0.8)]
        pts = [p for p in pts if f.isInside(p, 1e-3, True)] or [f.CenterOfMass]
        t = f.Surface.__class__.__name__
        if all(p.z < zt - 1 for p in pts) and all(p.y <= P["SaddleY1"] + 0.5 for p in pts):
            d = [math.hypot(p.x - ax, p.z - az0) - ri_y(p.y) for p in pts]
            if all(abs(x) < 0.02 for x in d) and t in ("Cone", "BSplineSurface", "Cylinder", "Toroid"):
                groups["SH_SADDLE"].append(i + 1); continue
        if t == "Cylinder" and abs(f.Surface.Radius - P["SleeveIR"]) < 1e-3 and abs(f.Surface.Axis.z) > 0.99:
            groups["SH_BORE"].append(i + 1); continue
        if t == "Plane" and abs(f.CenterOfMass.z - zt) < 1e-6 and f.Area < 1.2 * math.pi * (ro ** 2 - ri ** 2):
            c = f.CenterOfMass
            for k in (1, 2, 3):
                if math.hypot(c.x - P["Bottle%dX" % k], c.y - P["BottleY"]) < ro:
                    if k == L["pump_bottle"]:
                        groups["RINGPF" if c.y > P["BottleY"] else "RINGPR"].append(i + 1)
                    else:
                        groups["RING%d" % (others.index(k) + 1)].append(i + 1)
    for k, v in groups.items():
        if not v:
            raise RuntimeError("face group %s is empty" % k)
    return groups


# ============================================================ mesh
def write_geo(path_geo, brep_name, groups, P, M):
    sx, sy = P["SleeveX"], P["SleeveY"]
    boxes, sizes = [], []
    for b in M["boxes_in"]:
        rel = b.get("relative_to", "sleeve")
        ox, oy = (sx, 0.0) if rel == "sleeve" else (0.0, 0.0)
        x0, x1, y0, y1, z0, z1 = b["box"]
        boxes.append((ox + x0 * IN, ox + x1 * IN, oy + y0 * IN, oy + y1 * IN, z0 * IN, z1 * IN))
        sizes.append(M["Lf"] if b.get("size") == "Lf" else float(b["size"]))
    for k in M.get("slot_boxes_bottles", []):
        x = P["Bottle%dX" % k]
        boxes.append((x - 0.75 * IN, x + 0.75 * IN, P["BottleY"] - 0.3 * IN, P["BottleY"] + 0.3 * IN, -1.0 * IN, 0.1 * IN))
        sizes.append(M["Lf"])
    lines = ['SetFactory("OpenCASCADE");', 'Merge "%s";' % brep_name,
             "Mesh.ElementOrder = 2;", "Mesh.SecondOrderLinear = 1;", "Mesh.HighOrderOptimize = 0;",
             "Mesh.Algorithm = 6;", "Mesh.Algorithm3D = %d;" % M.get("algorithm3d", 10),
             "Mesh.Optimize = 1;", "Mesh.OptimizeNetgen = 1;",
             "Mesh.MeshSizeFromPoints = 0;", "Mesh.MeshSizeExtendFromBoundary = 0;",
             "Mesh.MeshSizeFromCurvature = %d;" % M["curv"], "Mesh.MeshSizeMin = %.3f;" % (min(sizes + [M["Lf"]]) * 0.35),
             "Mesh.MeshSizeMax = %.3f;" % M["Lg"], "General.NumThreads = %d;" % M.get("threads", 1),
             "Mesh.MaxNumThreads3D = %d;" % M.get("threads", 1), "Mesh.RandomSeed = 1;"]
    fid, flist = 1, []
    for b, hb in zip(boxes, sizes):
        lines += ["Field[%d] = Box;" % fid,
                  "Field[%d].VIn = %.4f; Field[%d].VOut = %.4f;" % (fid, hb, fid, M["Lg"]),
                  "Field[%d].XMin = %.4f; Field[%d].XMax = %.4f;" % (fid, b[0], fid, b[1]),
                  "Field[%d].YMin = %.4f; Field[%d].YMax = %.4f;" % (fid, b[2], fid, b[3]),
                  "Field[%d].ZMin = %.4f; Field[%d].ZMax = %.4f;" % (fid, b[4], fid, b[5]),
                  "Field[%d].Thickness = %.4f;" % (fid, 6.0),
                  "Field[%d] = Restrict; Field[%d].InField = %d; Field[%d].VolumesList = {1}; Field[%d].IncludeBoundary = 1;"
                  % (fid + 1, fid + 1, fid, fid + 1, fid + 1)]
        flist.append(fid + 1); fid += 2
    lines += ["Field[%d] = Min; Field[%d].FieldsList = {%s};" % (fid, fid, ", ".join(map(str, flist))),
              "Background Field = %d;" % fid, 'Physical Volume("SHELF", 1) = {1};']
    pid = 10
    for name, ids in groups.items():
        lines.append('Physical Surface("%s", %d) = {%s};' % (name, pid, ", ".join(map(str, ids)))); pid += 1
    lines += ["Mesh 3;", 'Save "%s";' % os.path.basename(path_geo).replace(".geo", ".msh")]
    with open(path_geo, "w") as f:
        f.write("\n".join(lines) + "\n")


def read_msh22(path):
    names, nid, xyz, tets, tris = {}, [], [], [], []
    with open(path) as f:
        sec = None
        for line in f:
            if line.startswith("$"):
                sec = line.strip()[1:]
                if sec.startswith("End"):
                    sec = None
                continue
            if sec == "Elements":
                p = line.split()
                if len(p) < 4:
                    continue
                et, nt = int(p[1]), int(p[2])
                if et == 11:
                    tets.append((int(p[3]), list(map(int, p[3 + nt:]))))
                elif et == 9:
                    tris.append((int(p[3]), list(map(int, p[3 + nt:]))))
            elif sec == "Nodes":
                p = line.split()
                if len(p) == 4:
                    nid.append(int(p[0])); xyz.append((float(p[1]), float(p[2]), float(p[3])))
            elif sec == "PhysicalNames":
                p = line.split()
                if len(p) >= 3:
                    names[int(p[1])] = p[2].strip('"')
    return np.array(nid), np.array(xyz), tets, tris, names


def build_model(msh_path):
    nid, xyz, tets, tris, names = read_msh22(msh_path)
    idx = {n: i for i, n in enumerate(nid)}
    E = np.array([[c[k] for k in GMSH2CCX_TET10] for _, c in tets])
    X = xyz
    P_ = lambda n: X[idx[n]]
    bad = sum(1 for e in E[:2000] if np.linalg.norm(P_(e[8]) - 0.5 * (P_(e[1]) + P_(e[3]))) > 0.2 * np.linalg.norm(P_(e[1]) - P_(e[3])))
    if bad > 20:
        raise RuntimeError("TET10 node order mismatch (%d of 2000)" % bad)
    fmap = {}
    for ei, e in enumerate(E):
        for fn, (a, b, c) in CCX_TET_FACES.items():
            fmap[tuple(sorted((e[a], e[b], e[c])))] = (ei + 1, fn)
    surf, area = {}, {}
    for phys, c in tris:
        nm = names.get(phys, str(phys))
        key = tuple(sorted(c[:3]))
        if key not in fmap:
            raise RuntimeError("surface triangle not on a tet face")
        surf.setdefault(nm, []).append(fmap[key])
        p0, p1, p2 = P_(c[0]), P_(c[1]), P_(c[2])
        area[nm] = area.get(nm, 0.0) + 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0))
        surf.setdefault(nm + "#nodes", set()).update(c)
    return dict(nid=nid, xyz=xyz, E=E, surf=surf, area=area, idx=idx)


def mesh_quality(Mo):
    X, idx = Mo["xyz"], Mo["idx"]
    C = np.vectorize(idx.get)(Mo["E"][:, :4])
    a, b, c, d = (X[C[:, k]] for k in range(4))
    vol = np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) / 6.0
    s2 = sum(np.einsum("ij,ij->i", p - q, p - q) for p, q in [(a, b), (a, c), (a, d), (b, c), (b, d), (c, d)])
    q = 12.0 * (3.0 * np.abs(vol)) ** (2.0 / 3.0) / s2
    le = np.sqrt(s2 / 6.0)
    return dict(elements=int(len(Mo["E"])), nodes=int(len(Mo["nid"])), equations_approx=int(3 * len(Mo["nid"])),
                n_inverted=int((vol <= 0).sum()), q_min=round(float(q.min()), 4), q_mean=round(float(q.mean()), 4),
                n_q_lt_0p2=int((q < 0.2).sum()), h_mean_mm=round(float(le.mean()), 3), h_min_mm=round(float(le.min()), 3),
                volume_mm3=float(np.abs(vol).sum()))


# ============================================================ CalculiX
def write_inp(path, Mo, P, cfg, bc):
    X, nid, E, surf, area = Mo["xyz"], Mo["nid"], Mo["E"], Mo["surf"], Mo["area"]
    mat, L = cfg["material"], cfg["loads"]
    out = []
    w = out.append
    w("** ShowerShelf FEM screening (fixed mount, idealised) -- written by ShowerShelf_FEM_Screening.py %s" % SCRIPT_VERSION)
    w("** units: mm, N, MPa, t")
    w("*NODE, NSET=NALL")
    for n, p in zip(nid, X):
        w("%d, %.6f, %.6f, %.6f" % (n, p[0], p[1], p[2]))
    w("*ELEMENT, TYPE=C3D10, ELSET=SHELF")
    for i, e in enumerate(E):
        w("%d, %s," % (i + 1, ", ".join(map(str, e[:8])))); w(", ".join(map(str, e[8:])))

    def nset(name, nodes):
        w("*NSET, NSET=%s" % name)
        nodes = sorted(nodes)
        for k in range(0, len(nodes), 12):
            w(", ".join(map(str, nodes[k:k + 12])) + ",")
    w("*MATERIAL, NAME=%s" % mat["name"]); w("*ELASTIC"); w("%.6g, %.6g" % (mat["E_MPa"], mat["nu"]))
    w("*DENSITY"); w("%.6g" % mat["rho_t_mm3"])
    w("*SOLID SECTION, ELSET=SHELF, MATERIAL=%s" % mat["name"])
    sad = surf["SH_SADDLE#nodes"]
    bore = surf["SH_BORE#nodes"] - sad
    zmax = bc.get("bore_fixed_zmax_in")
    if zmax is not None:
        bore = {n for n in bore if X[Mo["idx"][n]][2] <= zmax * IN + 1e-6}
    nset("FIX_SADDLE", sad); nset("FIX_BORE", bore)
    w("*STEP"); w("*STATIC")
    w("*BOUNDARY"); w("FIX_SADDLE, 1, 3, 0.0"); w("FIX_BORE, 1, 3, 0.0")
    w("*DLOAD"); w("SHELF, GRAV, %.6g, 0., 0., -1." % G_MM)
    W = L["bottle_mass_kg"] * 9.81
    Ap = area["RINGPF"] + area["RINGPR"]
    pr = {"RING1": W / area["RING1"], "RING2": W / area["RING2"], "RINGPF": W / Ap, "RINGPR": W / Ap}
    Fp = L["pump_N"]
    if L.get("offcentre"):
        pr["RINGPF"] += Fp / area["RINGPF"]
    else:
        pr["RINGPF"] += Fp / Ap; pr["RINGPR"] += Fp / Ap
    w("*DLOAD")
    for nm, p in pr.items():
        for e, fn in surf[nm]:
            w("%d, P%d, %.8g" % (e, fn, p))
    w("*NODE FILE"); w("U")
    w("*EL FILE"); w("S")
    w("*NODE PRINT, NSET=FIX_SADDLE, TOTALS=ONLY"); w("RF")
    w("*NODE PRINT, NSET=FIX_BORE, TOTALS=ONLY"); w("RF")
    w("*END STEP")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    return dict(applied_N=3 * W + Fp, bottle_weight_N=W, pressures_MPa=pr, ring_area_mm2=dict(area),
                n_fix_saddle=len(sad), n_fix_bore=len(bore))


def run_ccx(exe, workdir, job, threads):
    env = dict(os.environ)
    for k in ("OMP_NUM_THREADS", "CCX_NPROC_EQUATION_SOLVER", "CCX_NPROC_STIFFNESS", "CCX_NPROC_RESULTS"):
        env[k] = str(threads)
    with open(os.path.join(workdir, job + ".log"), "w") as lg:
        r = subprocess.run([exe, "-i", job], cwd=workdir, stdout=lg, stderr=subprocess.STDOUT, env=env)
    return r.returncode


def read_frd(path):
    res, nid, nxyz = {}, [], []
    with open(path) as f:
        mode = block = None; ids = []; vals = []
        for line in f:
            if line.startswith("    2C"):
                mode = "nodes"; continue
            if line.startswith("  100C"):
                mode = "res"; block = None; ids = []; vals = []; continue
            if line.startswith(" -3"):
                if mode == "res" and block:
                    res[block] = (np.array(ids), np.array(vals))
                mode = None; continue
            if mode == "nodes" and line.startswith(" -1"):
                nid.append(int(line[3:13])); nxyz.append((float(line[13:25]), float(line[25:37]), float(line[37:49])))
            elif mode == "res":
                if line.startswith(" -4"):
                    block = line.split()[1]
                elif line.startswith(" -1"):
                    s = line[13:].rstrip("\n")
                    ids.append(int(line[3:13])); vals.append([float(s[i:i + 12]) for i in range(0, len(s), 12) if s[i:i + 12].strip()])
    return dict(nid=np.array(nid), xyz=np.array(nxyz), res=res)


def read_dat_totals(path):
    out = {}
    txt = open(path).read()
    for m in re.finditer(r"total force \(fx,fy,fz\) for set (\S+) and time\s+(\S+)\s*\n\s*\n?\s*(\S+)\s+(\S+)\s+(\S+)", txt):
        out[m.group(1)] = [float(m.group(3)), float(m.group(4)), float(m.group(5))]
    return out


def solver_warnings(workdir, job):
    txt = ""
    for ext in (".log", ".sta"):
        p = os.path.join(workdir, job + ext)
        if os.path.exists(p):
            txt += open(p, errors="ignore").read()
    warn = [l.strip() for l in txt.splitlines() if re.search(r"warning|error|\*ERROR|singular|nonpositive|negative jacobian", l, re.I)]
    finished = "Job finished" in txt
    return finished, warn[:20]


# ============================================================ results
def principal(S):
    sxx, syy, szz, sxy, syz, szx = S.T
    vm = np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))
    T = np.zeros((len(S), 3, 3))
    T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = sxx, syy, szz
    T[:, 0, 1] = T[:, 1, 0] = sxy; T[:, 1, 2] = T[:, 2, 1] = syz; T[:, 0, 2] = T[:, 2, 0] = szx
    return vm, np.linalg.eigvalsh(T)[:, ::-1]


def region_mask(X, P, R):
    """Region from config: box in inches (x relative to the sleeve centre) and/or radial band about the sleeve."""
    m = np.ones(len(X), bool)
    sx, sy = P["SleeveX"], P["SleeveY"]
    if "box" in R:
        x0, x1, y0, y1, z0, z1 = R["box"]
        m &= (X[:, 0] >= sx + x0 * IN) & (X[:, 0] <= sx + x1 * IN) & (X[:, 1] >= y0 * IN) & (X[:, 1] <= y1 * IN) \
            & (X[:, 2] >= z0 * IN) & (X[:, 2] <= z1 * IN)
    if "r_sleeve_in" in R:
        r = np.hypot(X[:, 0] - sx, X[:, 1] - sy)
        m &= (r >= R["r_sleeve_in"][0] * IN) & (r <= R["r_sleeve_in"][1] * IN)
    return m


def surface_tris(E):
    F = np.vstack([E[:, list(f)] for f in CCX_TET_FACES.values()])
    key = np.sort(F, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return F[cnt[inv.ravel()] == 1]


def summarize(frd, Mo, P, cfg, setup):
    nid = Mo["nid"]
    fi = {n: i for i, n in enumerate(frd["nid"])}
    rows = np.array([fi[n] for n in nid])
    X = frd["xyz"][rows]
    Ub = frd["res"]["DISP"]; ui = {n: i for i, n in enumerate(Ub[0])}
    U = Ub[1][[ui[n] for n in nid]][:, :3]
    Sb = frd["res"]["STRESS"]; si = {n: i for i, n in enumerate(Sb[0])}
    S = Sb[1][[si[n] for n in nid]][:, :6]
    vm, pr = principal(S)
    excl = Mo["surf"]["SH_SADDLE#nodes"] | Mo["surf"]["SH_BORE#nodes"]
    keep = np.array([n not in excl for n in nid])
    near = lambda x, y, z: int(np.argmin((X[:, 0] - x) ** 2 + (X[:, 1] - y) ** 2 + (X[:, 2] - z) ** 2))
    o = {}
    o["max_down_disp_mm"] = round(float(-U[:, 2].min()), 4); o["max_down_disp_at_mm"] = X[U[:, 2].argmin()].round(1).tolist()
    um = np.linalg.norm(U, axis=1)
    o["max_total_disp_mm"] = round(float(um.max()), 4)
    names = {cfg["loads"]["pump_bottle"]: ("RINGPF", "RINGPR")}
    others = [k for k in (1, 2, 3) if k != cfg["loads"]["pump_bottle"]]
    names[others[0]] = ("RING1",); names[others[1]] = ("RING2",)
    for k, grp in sorted(names.items()):
        ns = set().union(*[Mo["surf"][g + "#nodes"] for g in grp])
        sel = np.array([i for i, n in enumerate(nid) if n in ns])
        o["bottle%d_base_mean_Uz_mm" % k] = round(float(U[sel, 2].mean()), 4)
        A = np.c_[X[sel, 0] - X[sel, 0].mean(), X[sel, 1] - X[sel, 1].mean(), np.ones(len(sel))]
        cx, cy, _ = np.linalg.lstsq(A, U[sel, 2], rcond=None)[0]
        o["bottle%d_base_tilt_deg_aboutY_aboutX" % k] = [round(math.degrees(math.atan(cx)), 3), round(math.degrees(math.atan(cy)), 3)]
    # left end of the rim (crest at the extreme left, on the capsule centreline)
    iL = near(P["ShelfXmin"] + P["RimThk"] / 2, P["ShelfYc"], 0.0)
    o["left_rim_end_Uz_mm"] = round(float(U[iL, 2]), 4); o["left_rim_end_node_at_mm"] = X[iL].round(1).tolist()
    iFL = near(P["Bottle3X"], P["ShelfDepth"] - P["RimThk"] / 2, 0.0)
    o["left_front_rim_Uz_at_bottle3_mm"] = round(float(U[iFL, 2]), 4)
    iF = near(P["Bottle3X"], P["ShelfDepth"] - 1.6, 0.0); iR = near(P["Bottle3X"], 1.6, 0.0)
    o["left_end_twist_deg"] = round(math.degrees(math.atan2(U[iF, 2] - U[iR, 2], X[iF, 1] - X[iR, 1])), 3)
    o["max_vonMises_MPa_excl_constrained"] = round(float(vm[keep].max()), 3)
    o["max_vonMises_at_mm"] = X[np.nonzero(keep)[0][vm[keep].argmax()]].round(1).tolist()
    o["max_principal_MPa_excl_constrained"] = round(float(pr[keep, 0].max()), 3)
    o["max_principal_at_mm"] = X[np.nonzero(keep)[0][pr[keep, 0].argmax()]].round(1).tolist()
    o["max_vonMises_MPa_all_nodes"] = round(float(vm.max()), 3)
    reg = {}
    for nm, R in cfg["regions"].items():
        m = region_mask(X, P, R) & keep
        if not m.any():
            reg[nm] = dict(n=0); continue
        iv = np.nonzero(m)[0][vm[m].argmax()]; ip = np.nonzero(m)[0][pr[m, 0].argmax()]
        reg[nm] = dict(n=int(m.sum()), vm_max=round(float(vm[iv]), 3), vm_max_at_mm=X[iv].round(1).tolist(),
                       vm_p99=round(float(np.percentile(vm[m], 99)), 3), p1_max=round(float(pr[ip, 0]), 3),
                       p1_max_at_mm=X[ip].round(1).tolist(), p1_p99=round(float(np.percentile(pr[m, 0], 99)), 3))
    o["regions"] = reg
    T = surface_tris(Mo["E"][:, :4])
    used = np.unique(T)
    rmap = {n: i for i, n in enumerate(nid)}
    li = np.array([rmap[n] for n in used])
    remap = {n: k for k, n in enumerate(used)}
    Tl = np.vectorize(remap.get)(T)
    surf = dict(X=X[li].astype(np.float32), U=U[li].astype(np.float32), vm=vm[li].astype(np.float32),
                p1=pr[li, 0].astype(np.float32), T=Tl.astype(np.int32),
                fixed=np.array([n in excl for n in used]))
    return o, surf


# ============================================================ plots
VIEWS = {"front": ((0.45, -0.75, -0.55), (0, 0, 1)), "rear": ((0.45, 0.75, -0.55), (0, 0, 1)),
         "top": ((0, 0, -1), (0, 1, 0)), "bottom": ((0.3, 0.5, 0.8), (0, 1, 0)),
         "rear_left": ((0.75, 0.45, -0.45), (0, 0, 1))}


def _cam(dirv, up):
    d = -np.array(dirv, float); d /= np.linalg.norm(d)
    u = np.array(up, float); u = u - d * u.dot(d); u /= np.linalg.norm(u)
    return np.vstack([np.cross(u, d), u, d])


def draw_field(ax, S, field, view, vmin, vmax, cmap, deform=1.0, crop_in=None):
    import matplotlib
    from matplotlib.collections import PolyCollection
    X = S["X"] + deform * S["U"]
    val = {"Utot": np.linalg.norm(S["U"], axis=1), "Uz": S["U"][:, 2], "vm": S["vm"], "p1": S["p1"]}[field]
    T = S["T"]
    tri = X[T] / IN
    if crop_in is not None:
        c = tri.mean(1)
        x0, x1, y0, y1, z0, z1 = crop_in
        m = (c[:, 0] > x0) & (c[:, 0] < x1) & (c[:, 1] > y0) & (c[:, 1] < y1) & (c[:, 2] > z0) & (c[:, 2] < z1)
        tri, T = tri[m], T[m]
    R = _cam(*VIEWS[view])
    V = tri @ R.T
    n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-15
    n[n[:, 2] < 0] *= -1
    Lv = np.array([0.3, 0.6, 1.0]); Lv /= np.linalg.norm(Lv)
    k = 0.62 + 0.30 * np.clip(n @ Lv, 0, 1) + 0.08 * n[:, 2]
    tv = val[T].mean(1)
    cm = matplotlib.colormaps[cmap]
    col = cm(np.clip((tv - vmin) / (vmax - vmin + 1e-30), 0, 1))
    col[:, :3] *= k[:, None]
    order = np.argsort(V[:, :, 2].mean(1))
    pc = PolyCollection(V[order][:, :, :2], facecolors=np.clip(col[order], 0, 1), edgecolors="none", antialiased=False)
    ax.add_collection(pc)
    ax.set_xlim(V[:, :, 0].min(), V[:, :, 0].max()); ax.set_ylim(V[:, :, 1].min(), V[:, :, 1].max())
    ax.set_aspect("equal"); ax.axis("off")
    return val


FIELD_INFO = {"Utot": ("Total displacement", "mm", "turbo"), "Uz": ("Vertical displacement Uz", "mm", "turbo"),
              "vm": ("von Mises stress", "MPa", "turbo"), "p1": ("Max principal stress", "MPa", "coolwarm")}


def plot_compare(surfs, tags, field, view, path, vmin, vmax, title, crop_in=None, note=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import Normalize
    nm, unit, cmap = FIELD_INFO[field]
    fig, axs = plt.subplots(1, len(tags), figsize=(7.5 * len(tags), 5.6), dpi=130)
    axs = np.atleast_1d(axs)
    for ax, t, S in zip(axs, tags, surfs):
        val = draw_field(ax, S, field, view, vmin, vmax, cmap, crop_in=crop_in)
        ax.set_title("%s   (max %.3g, min %.3g %s)" % (t, val.max(), val.min(), unit), fontsize=11)
    sm = ScalarMappable(norm=Normalize(vmin, vmax), cmap=matplotlib.colormaps[cmap])
    cb = fig.colorbar(sm, ax=list(axs), shrink=0.8, pad=0.01); cb.set_label("%s [%s]" % (nm, unit))
    fig.suptitle(title + ("\n" + note if note else ""), fontsize=12)
    fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def plot_bars(summaries, tags, path, metrics):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, len(metrics), figsize=(3.3 * len(metrics), 4.2), dpi=130)
    for ax, (lab, getter, unit) in zip(np.atleast_1d(axs), metrics):
        v = [getter(summaries[t]) for t in tags]
        b = ax.bar(range(len(tags)), v, color=["#7f7f7f", "#1f77b4", "#ff7f0e", "#2ca02c"][:len(tags)])
        ax.set_xticks(range(len(tags))); ax.set_xticklabels(tags, rotation=25, ha="right", fontsize=8)
        ax.set_title("%s\n[%s]" % (lab, unit), fontsize=9)
        for r, x in zip(b, v):
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), "%.3g" % x, ha="center", va="bottom", fontsize=8)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


# ============================================================ driver
def run_model(cfg, mdl, root, versions, fh):
    tag = mdl["tag"]
    W = os.path.join(root, cfg["work_dir"], "runs", tag); os.makedirs(W, exist_ok=True)
    RES = os.path.join(root, cfg["work_dir"], "results"); os.makedirs(RES, exist_ok=True)
    bc = dict(cfg["bc"]); bc.update(mdl.get("bc", {}))
    t = {}
    t0 = time.time()
    shelf, P, finfo = load_model(os.path.join(root, mdl["fcstd"]))
    shelf_i = imprint_rings(shelf, P, cfg["loads"])
    groups = classify_faces(shelf_i, P, cfg["loads"])
    brep = os.path.join(W, tag + ".brep"); shelf_i.exportBrep(brep)
    write_geo(os.path.join(W, tag + ".geo"), tag + ".brep", groups, P, cfg["mesh"])
    t["geometry_s"] = round(time.time() - t0, 1); log("%s: geometry %.1f s (V=%.1f mm3)" % (tag, t["geometry_s"], finfo["volume_mm3"]), fh)
    t1 = time.time()
    with open(os.path.join(W, tag + "_gmsh.log"), "w") as lg:
        r = subprocess.run([cfg["gmsh_exe"], tag + ".geo", "-format", "msh22", "-nt", str(cfg["mesh"].get("threads", 1)), "-"],
                           cwd=W, stdout=lg, stderr=subprocess.STDOUT)
    if r.returncode != 0 or not os.path.exists(os.path.join(W, tag + ".msh")):
        raise RuntimeError("gmsh failed (see %s_gmsh.log)" % tag)
    t["meshing_s"] = round(time.time() - t1, 1)
    t2 = time.time()
    Mo = build_model(os.path.join(W, tag + ".msh"))
    q = mesh_quality(Mo)
    if q["n_inverted"]:
        raise RuntimeError("mesh has %d inverted elements" % q["n_inverted"])
    setup = write_inp(os.path.join(W, tag + ".inp"), Mo, P, cfg, bc)
    t["deck_s"] = round(time.time() - t2, 1)
    log("%s: mesh %.1f s, %d elements, %d nodes, q_mean %.3f; deck %.1f s" % (tag, t["meshing_s"], q["elements"], q["nodes"], q["q_mean"], t["deck_s"]), fh)
    t3 = time.time()
    rc = run_ccx(cfg["ccx_exe"], W, tag, cfg["threads"])
    t["solver_s"] = round(time.time() - t3, 1)
    finished, warns = solver_warnings(W, tag)
    if rc != 0 or not finished or not os.path.exists(os.path.join(W, tag + ".frd")):
        raise RuntimeError("CalculiX failed (rc=%s, finished=%s): %s" % (rc, finished, warns))
    log("%s: CalculiX %.1f s (warnings: %d)" % (tag, t["solver_s"], len(warns)), fh)
    t4 = time.time()
    frd = read_frd(os.path.join(W, tag + ".frd"))
    summ, surf = summarize(frd, Mo, P, cfg, setup)
    tot = read_dat_totals(os.path.join(W, tag + ".dat"))
    Wshelf = cfg["material"]["rho_t_mm3"] * q["volume_mm3"] * G_MM
    summ["reactions_N"] = tot
    summ["equilibrium"] = dict(applied_external_N=round(setup["applied_N"], 4), shelf_self_weight_N=round(Wshelf, 4),
                               expected_total_down_N=round(setup["applied_N"] + Wshelf, 4),
                               sum_reaction_N=[round(sum(v[i] for v in tot.values()), 4) for i in range(3)])
    eq = summ["equilibrium"]
    eq["error_pct"] = round(100 * abs(eq["sum_reaction_N"][2] - eq["expected_total_down_N"]) / eq["expected_total_down_N"], 4)
    summ["model"] = dict(tag=tag, file=mdl["fcstd"], sha256_16=finfo["sha256_16"], volume_mm3=round(finfo["volume_mm3"], 1),
                         volume_in3=round(finfo["volume_mm3"] / IN ** 3, 4),
                         mass_g=round(finfo["volume_mm3"] * cfg["material"]["rho_t_mm3"] * 1e6, 1),
                         solid_valid=finfo["valid"], solids=finfo["solids"], sleeve_top_Z_in=round(P["SleeveTopZ"] / IN, 4))
    summ["mesh"] = q; summ["mesh"]["level"] = cfg["mesh"]["name"]
    summ["bc"] = dict(bc, n_fix_saddle=setup["n_fix_saddle"], n_fix_bore=setup["n_fix_bore"])
    summ["loads"] = dict(cfg["loads"], pressures_MPa={k: round(v, 6) for k, v in setup["pressures_MPa"].items()},
                         ring_area_mm2={k: round(v, 2) for k, v in setup["ring_area_mm2"].items() if not k.endswith("#nodes")})
    summ["material"] = cfg["material"]
    summ["solver"] = dict(versions, finished=finished, warnings=warns)
    t["postprocess_s"] = round(time.time() - t4, 1)
    t["total_s"] = round(time.time() - t0, 1)
    summ["timing_s"] = t
    json.dump(summ, open(os.path.join(RES, tag + "_summary.json"), "w"), indent=1)
    np.savez_compressed(os.path.join(RES, tag + "_surface.npz"), **surf)
    log("%s: post %.1f s; total %.1f s; B3 base Uz %.3f mm, max down %.3f mm, eq. err %.3f %%"
        % (tag, t["postprocess_s"], t["total_s"], summ["bottle3_base_mean_Uz_mm"], summ["max_down_disp_mm"], eq["error_pct"]), fh)
    # Journal only a newly completed solver run, after summary is safely written.
    if os.environ.get("FREECAD_JOURNAL_PROJECT"):
        _journal_bridge().record_fem("screening", summ,
            os.path.join(RES, tag + "_summary.json"),
            cfg.get("_journal_config_path"), os.path.join(root, mdl["fcstd"]), W)
    if cfg.get("keep_frd", True) is False:
        os.remove(os.path.join(W, tag + ".frd"))
    return summ


def report(cfg, root, fh=None):
    RES = os.path.join(root, cfg["work_dir"], "results")
    IMG = os.path.join(root, cfg["work_dir"], "images"); os.makedirs(IMG, exist_ok=True)
    tags = [m["tag"] for m in cfg["models"] if os.path.exists(os.path.join(RES, m["tag"] + "_summary.json"))]
    S = {t: json.load(open(os.path.join(RES, t + "_summary.json"))) for t in tags}
    F = {t: dict(np.load(os.path.join(RES, t + "_surface.npz"))) for t in tags}
    base = cfg.get("baseline", tags[0])
    t_plot = time.time()
    pt = cfg["plots"]
    umin = min(float(F[t]["U"][:, 2].min()) for t in tags)
    for p in pt["compare"]:
        sel = [t for t in p.get("tags", tags) if t in tags]
        f = p["field"]
        if f == "Uz":
            lo, hi = umin, max(0.0, max(float(F[t]["U"][:, 2].max()) for t in sel))
        elif f == "Utot":
            lo, hi = 0.0, max(float(np.linalg.norm(F[t]["U"], axis=1).max()) for t in sel)
        else:
            lo, hi = p.get("range", (0, 30))
        plot_compare([F[t] for t in sel], sel, f, p["view"], os.path.join(IMG, p["file"]), lo, hi,
                     p["title"], crop_in=p.get("crop_in"), note=p.get("note", ""))
    def g(path):
        def f(s):
            v = s
            for k in path:
                v = v[k]
            return abs(v) if isinstance(v, (int, float)) else v
        return f
    metrics = [("Leftmost bottle base\n|Uz| mean", g(["bottle3_base_mean_Uz_mm"]), "mm"),
               ("Left rim end |Uz|", g(["left_rim_end_Uz_mm"]), "mm"),
               ("Max downward disp.", g(["max_down_disp_mm"]), "mm"),
               ("Left arm root p1 max", g(["regions", "left arm root (rear opening)", "p1_max"]), "MPa"),
               ("Left arm root p1 p99", g(["regions", "left arm root (rear opening)", "p1_p99"]), "MPa"),
               ("Saddle front corner\nvM max", g(["regions", "saddle front end / floor", "vm_max"]), "MPa")]
    plot_bars(S, tags, os.path.join(IMG, pt.get("bars_file", "compare_bars.png")), metrics)
    t_plot = time.time() - t_plot
    # ---- markdown comparison
    L = []
    w = L.append
    w("# FEM screening comparison (auto-generated)")
    w("")
    w("Generated %s by ShowerShelf_FEM_Screening.py %s. **Idealised fixed-mount model**: the saddle inner surface and the sleeve bore "
      "(see BC column) are fully fixed. Use it to rank geometry. It does not predict installed deflection." % (time.strftime("%Y-%m-%d %H:%M"), SCRIPT_VERSION))
    w("")
    hdr = "| Quantity | " + " | ".join(tags) + " |"
    w(hdr); w("|" + "---|" * (len(tags) + 1))
    def row(lab, fn, fmt="%.3f"):
        vals = []
        for t in tags:
            try:
                v = fn(S[t]); vals.append(fmt % v if isinstance(v, (int, float)) else str(v))
            except Exception:
                vals.append("-")
        w("| %s | %s |" % (lab, " | ".join(vals)))
    row("Model file (SHA-256/16)", lambda s: "%s (%s)" % (s["model"]["file"], s["model"]["sha256_16"]), "%s")
    row("Bore fixed up to Z [in]", lambda s: "full height" if s["bc"].get("bore_fixed_zmax_in") is None else "%.3f" % s["bc"]["bore_fixed_zmax_in"], "%s")
    row("Volume [in^3]", lambda s: s["model"]["volume_in3"], "%.4f")
    row("PA12 mass [g]", lambda s: s["model"]["mass_g"], "%.1f")
    row("Leftmost bottle base mean Uz [mm]", lambda s: s["bottle3_base_mean_Uz_mm"])
    row("Leftmost bottle base tilt about Y / X [deg]", lambda s: "%.2f / %.2f" % tuple(s["bottle3_base_tilt_deg_aboutY_aboutX"]), "%s")
    row("Left rim end Uz [mm]", lambda s: s["left_rim_end_Uz_mm"])
    row("Front rim at leftmost bottle Uz [mm]", lambda s: s["left_front_rim_Uz_at_bottle3_mm"])
    row("Max downward displacement [mm]", lambda s: s["max_down_disp_mm"])
    row("Left-end twist [deg]", lambda s: s["left_end_twist_deg"])
    row("Max von Mises, excl. fixed nodes [MPa]", lambda s: s["max_vonMises_MPa_excl_constrained"], "%.2f")
    row("Max principal, excl. fixed nodes [MPa]", lambda s: s["max_principal_MPa_excl_constrained"], "%.2f")
    for rn in cfg["regions"]:
        row("%s: p1 max / p99 [MPa]" % rn, lambda s, rn=rn: "%.2f / %.2f" % (s["regions"][rn]["p1_max"], s["regions"][rn]["p1_p99"]), "%s")
        row("%s: vM max / p99 [MPa]" % rn, lambda s, rn=rn: "%.2f / %.2f" % (s["regions"][rn]["vm_max"], s["regions"][rn]["vm_p99"]), "%s")
    row("Reaction sum Fz / expected [N]", lambda s: "%.3f / %.3f" % (s["equilibrium"]["sum_reaction_N"][2], s["equilibrium"]["expected_total_down_N"]), "%s")
    row("Elements / nodes", lambda s: "%d / %d" % (s["mesh"]["elements"], s["mesh"]["nodes"]), "%s")
    row("Mesh q_mean / q_min / inverted", lambda s: "%.3f / %.3f / %d" % (s["mesh"]["q_mean"], s["mesh"]["q_min"], s["mesh"]["n_inverted"]), "%s")
    row("Solver finished / warnings", lambda s: "%s / %d" % (s["solver"]["finished"], len(s["solver"]["warnings"])), "%s")
    row("Time: geometry / mesh / deck / solve / post [s]", lambda s: " / ".join("%.0f" % s["timing_s"][k] for k in
        ("geometry_s", "meshing_s", "deck_s", "solver_s", "postprocess_s")), "%s")
    row("Time total [s]", lambda s: s["timing_s"]["total_s"], "%.0f")
    w("")
    if base in S:
        w("Changes relative to %s:" % base)
        w("")
        for t in tags:
            if t == base:
                continue
            b, s = S[base], S[t]
            w("* %s: leftmost bottle base Uz %+.1f %%, left rim end Uz %+.1f %%, max down %+.1f %%, mass %+.1f %%."
              % (t, 100 * (s["bottle3_base_mean_Uz_mm"] / b["bottle3_base_mean_Uz_mm"] - 1),
                 100 * (s["left_rim_end_Uz_mm"] / b["left_rim_end_Uz_mm"] - 1),
                 100 * (s["max_down_disp_mm"] / b["max_down_disp_mm"] - 1),
                 100 * (s["model"]["mass_g"] / b["model"]["mass_g"] - 1)))
    w("")
    w("Plot time for this report: %.0f s." % t_plot)
    open(os.path.join(RES, cfg.get("report_file", "Screening_Comparison.md")), "w").write("\n".join(L) + "\n")
    if fh:
        log("report written (%d models, plots %.0f s)" % (len(tags), t_plot), fh)
    return S


def main(config_path, only=None, report_only=False):
    cfg = json.load(open(config_path))
    cfg["_journal_config_path"] = os.path.abspath(config_path)
    root = os.path.abspath(cfg.get("project_dir") or os.path.dirname(os.path.abspath(config_path)))
    wd = os.path.join(root, cfg["work_dir"]); os.makedirs(wd, exist_ok=True)
    fh = open(os.path.join(wd, "screening_log.txt"), "a")
    log("=== ShowerShelf_FEM_Screening %s, config %s" % (SCRIPT_VERSION, config_path), fh)
    versions = dict(script=SCRIPT_VERSION, calculix=tool_version(cfg["ccx_exe"], ["-v"]),
                    gmsh=tool_version(cfg["gmsh_exe"], ["--version"]), python=platform.python_version())
    try:
        import FreeCAD as App
        versions["freecad"] = ".".join(App.Version()[:3])
    except Exception:
        pass
    log("versions %s" % versions, fh)
    if not report_only:
        for m in cfg["models"]:
            if only and m["tag"] not in only:
                continue
            if m.get("reuse_summary"):
                log("%s: reusing validated result %s" % (m["tag"], m["reuse_summary"]), fh)
                continue
            try:
                run_model(cfg, m, root, versions, fh)
            except Exception as e:
                log("%s: FAILED %s" % (m["tag"], e), fh)
                raise
    S = report(cfg, root, fh)
    fh.close()
    return S


if (__name__ == "__main__" or os.environ.get("SHELF_FEM_RUN") == "1") and not os.environ.get("_SHELF_FEM_ACTIVE"):
    os.environ["_SHELF_FEM_ACTIVE"] = "1"       # freecadcmd may evaluate the file twice
    _cfg = os.environ.get("SHELF_FEM_CONFIG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "FEM_Screening_config.json")
    _only = [x for x in os.environ.get("SHELF_FEM_ONLY", "").split(",") if x] or None
    main(_cfg, only=_only, report_only=os.environ.get("SHELF_FEM_REPORT_ONLY") == "1")

# Optional engineering journal bridge; set FREECAD_JOURNAL_PROJECT to enable.
def _journal_bridge():
    import os, sys
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    import journal_integration
    return journal_integration
