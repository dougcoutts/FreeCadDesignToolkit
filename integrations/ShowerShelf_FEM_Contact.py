# -*- coding: utf-8 -*-
"""
ShowerShelf_FEM_Contact.py -- installed-condition (contact-supported) analysis, Phase 3B.

Method = the Phase 2 validated condensed unilateral-contact method (femcontact.py,
Phase2_FEM_Report.md section 6.2), wrapped in the Phase 3 accelerated workflow
(geometry, mesh, plots from ShowerShelf_FEM_Screening.py):

  1. V4/V3 ShelfSolid copied read-only, bottle rings imprinted, Gmsh C3D10 mesh
     (same 'coarse+' level and boxes as the screening).
  2. Retained interface = all corner nodes of the saddle inner (mating) surface and of
     the sleeve bore (full bore height; V4: Z -0.815 .. +1.000 in).
  3. CalculiX *SUBSTRUCTURE GENERATE -> reduced stiffness Kr (3 DOF per node)
     and, in parallel, a linear run with the interface fixed -> condensed load -R0.
  4. Frictionless unilateral contact on the reduced system against RIGID analytic
     surfaces: the tapered cylinder (nominal design diameter on the measured taper) and
     the Ø0.875 in tube, both with 0.010 in radial clearance; nominal installed
     position = shelf resting on the cylinder crown, tube centred in the bore.
     Penalty semismooth-Newton active set, kc = 1e5 N/mm; linearised radial gaps.
  5. CalculiX linear run with the interface displacements prescribed -> full fields;
     interface reactions = contact forces (checked).
  Variant 'tube_zmax_in': bore nodes above that Z are excluded from contact
  (isolates the effect of the longer sleeve engagement on the same structure).

Run:  set SHELF_CONTACT_CONFIG=...\\FEM_Contact_config.json
      "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" ShowerShelf_FEM_Contact.py
"""
import os, sys, json, math, re, time, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ShowerShelf_FEM_Screening as S

IN = 25.4
G_MM = 9810.0
VERSION = "1.0 (Phase 3B, 2026-11-16)"
S.PARAM_KEYS = tuple(S.PARAM_KEYS) + ("DesignDiaRear", "TubeOD", "SaddleClr", "SleeveTubeClr", "SleeveTopZ", "SleeveOR")


# ---------------------------------------------------------------- interface (Phase 2 femcontact.interface)
def interface(Mo, P, clr_saddle, clr_tube):
    X, idx = Mo["xyz"], Mo["idx"]
    out = {}
    cax, caz = P["SaddleAxisX"], P["SaddleAxisZ"] + clr_saddle          # cylinder crown touches the saddle crown
    rcyl = lambda y: P["DesignDiaRear"] / 2 - P["TaperSlope"] / 2 * (y - P["SaddleY0"])
    tx, ty, rt = P["SleeveX"], P["SleeveY"], P["TubeOD"] / 2
    for g, kind in (("SH_SADDLE", "cyl"), ("SH_BORE", "tube")):
        area = {}
        for e, fn in Mo["surf"][g]:
            el = Mo["E"][e - 1]
            c = [el[k] for k in S.CCX_TET_FACES[fn]]
            p = [X[idx[n]] for n in c]
            a = 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0]))
            for n in c:
                area[n] = area.get(n, 0.0) + a / 3.0
        for n, a in area.items():
            if n in out:
                continue
            x, y, z = X[idx[n]]
            if kind == "cyl":
                v = np.array([x - cax, 0.0, z - caz]); d = np.linalg.norm(v)
                out[n] = dict(kind=kind, n=v / d, g0=d - rcyl(y), area=a, xyz=(x, y, z))
            else:
                v = np.array([x - tx, y - ty, 0.0]); d = np.linalg.norm(v)
                out[n] = dict(kind=kind, n=v / d, g0=d - rt, area=a, xyz=(x, y, z))
    return out


# ---------------------------------------------------------------- decks
SPRING_K = 0.01


def _base(w, Mo, mat, springs_k=SPRING_K):
    X, nid, E = Mo["xyz"], Mo["nid"], Mo["E"]
    w("*NODE, NSET=NALL")
    for n, p in zip(nid, X):
        w("%d, %.6f, %.6f, %.6f" % (n, p[0], p[1], p[2]))
    w("*ELEMENT, TYPE=C3D10, ELSET=SHELF")
    for i, e in enumerate(E):
        w("%d, %s," % (i + 1, ", ".join(map(str, e[:8])))); w(", ".join(map(str, e[8:])))
    w("*MATERIAL, NAME=%s" % mat["name"]); w("*ELASTIC"); w("%.6g, %.6g" % (mat["E_MPa"], mat["nu"]))
    w("*DENSITY"); w("%.6g" % mat["rho_t_mm3"])
    w("*SOLID SECTION, ELSET=SHELF, MATERIAL=%s" % mat["name"])
    # Phase 2: 3 weak springs inside the sleeve wall at Z = 0 (r = 0.55 in, 120 deg apart)
    sp = []
    sx, sy = 0.0, 1.157 * IN
    for a in (90.0, 210.0, 330.0):
        tx, ty = sx + 0.55 * IN * math.cos(math.radians(a)), sy + 0.55 * IN * math.sin(math.radians(a))
        dd = (X[:, 0] - tx) ** 2 + (X[:, 1] - ty) ** 2 + (X[:, 2] - 0.0) ** 2
        sp.append(int(nid[int(np.argmin(dd))]))
    eid = len(E) + 1
    for dof in (1, 2, 3):
        w("*ELEMENT, TYPE=SPRING1, ELSET=ESPR%d" % dof)
        for n in sp:
            w("%d, %d" % (eid, n)); eid += 1
        w("*SPRING, ELSET=ESPR%d" % dof); w("%d" % dof); w("%.6g" % springs_k)
    return sp


def _nset(w, name, nodes):
    w("*NSET, NSET=%s" % name)
    nodes = sorted(nodes)
    for k in range(0, len(nodes), 12):
        w(", ".join(map(str, nodes[k:k + 12])) + ",")


def _loads(w, Mo, L):
    surf, area = Mo["surf"], Mo["area"]
    w("*DLOAD"); w("SHELF, GRAV, %.6g, 0., 0., -1." % G_MM)
    W = L["bottle_mass_kg"] * 9.81
    A3 = area["RINGPF"] + area["RINGPR"]
    pr = {"RING1": W / area["RING1"], "RING2": W / area["RING2"], "RINGPF": W / A3, "RINGPR": W / A3}
    Fp = L["pump_N"]
    if L.get("offcentre"):
        pr["RINGPF"] += Fp / area["RINGPF"]
    else:
        pr["RINGPF"] += Fp / A3; pr["RINGPR"] += Fp / A3
    w("*DLOAD")
    for nm, p in pr.items():
        for e, fn in surf[nm]:
            w("%d, P%d, %.8g" % (e, fn, p))
    return 3 * W + Fp, pr


def write_subgen(path, Mo, ret, mat):
    L = []; w = L.append
    _base(w, Mo, mat)
    _nset(w, "RET", ret)
    w("*STEP"); w("*SUBSTRUCTURE GENERATE")
    w("*RETAINED NODAL DOFS, SORTED=NO"); w("RET, 1, 3")
    w("*SUBSTRUCTURE MATRIX OUTPUT, STIFFNESS=YES, OUTPUT FILE=USERDEFINED, FILE NAME=%s_K"
      % os.path.splitext(os.path.basename(path))[0])
    w("*END STEP")
    open(path, "w").write("\n".join(L) + "\n")


def write_static(path, Mo, ret, mat, loads, prescribed=None):
    L = []; w = L.append
    sp = _base(w, Mo, mat)
    _nset(w, "RET", ret); _nset(w, "N_SPRINGS", sp)
    w("*STEP"); w("*STATIC"); w("*BOUNDARY")
    if prescribed is None:
        w("RET, 1, 3, 0.0")
    else:
        for n in ret:
            u = prescribed[n]
            for k in range(3):
                w("%d, %d, %d, %.10g" % (n, k + 1, k + 1, u[k]))
    applied, pr = _loads(w, Mo, loads)
    w("*NODE FILE"); w("U")
    w("*EL FILE"); w("S")
    w("*NODE PRINT, NSET=RET"); w("RF")
    w("*NODE PRINT, NSET=RET, TOTALS=ONLY"); w("RF")
    w("*NODE PRINT, NSET=N_SPRINGS"); w("U")
    w("*END STEP")
    open(path, "w").write("\n".join(L) + "\n")
    return dict(applied_N=applied, spring_nodes=sp, pressures=pr)


# ---------------------------------------------------------------- parsing
def read_kred(path):
    """CalculiX substructure stiffness (lower triangle, node list repeated per DOF in the header)."""
    with open(path) as f:
        txt = f.read()
    head, mat = txt.split("*MATRIX,TYPE=STIFFNESS")
    nodes = []
    for l in head.splitlines():
        if l.startswith("**") and re.match(r"\*\*\s+\d", l):
            nodes += [int(x) for x in l[2:].replace(",", " ").split()]
    n = len(nodes)
    body = "\n".join(l for l in mat.splitlines() if l.strip() and not l.lstrip().startswith("*"))
    vals = np.fromstring(body.replace(",", " "), sep=" ")
    if len(vals) != n * (n + 1) // 2:
        raise RuntimeError("kred size mismatch %d vs %d" % (len(vals), n * (n + 1) // 2))
    K = np.zeros((n, n))
    K[np.tril_indices(n)] = vals
    K = K + K.T - np.diag(np.diag(K))
    dofs, cnt = [], {}
    for nd in nodes:
        cnt[nd] = cnt.get(nd, 0) + 1
        dofs.append((nd, cnt[nd]))
    return dofs, K


def read_node_print(path):
    out, cur = {}, None
    for line in open(path):
        s = line.strip()
        if s.startswith("forces") or s.startswith("displacements"):
            m = re.search(r"for set (\S+)", s)
            cur = m.group(1) if m else None
            if cur and "total" not in s:
                out.setdefault(cur, {})
            else:
                cur = None
            continue
        if s.startswith("total"):
            cur = None; continue
        if cur and s:
            p = s.split()
            if len(p) in (4, 5) and p[0].isdigit():          # 5th token 'L' = local (transformed) system
                out[cur][int(p[0])] = np.array([float(v) for v in p[1:4]])
    return out


def read_totals(path):
    out = {}
    txt = open(path).read()
    for m in re.finditer(r"total force \(fx,fy,fz\) for set (\S+) and time\s+(\S+)\s*\n\s*\n?\s*(\S+)\s+(\S+)\s+(\S+)", txt):
        out[m.group(1)] = [float(m.group(3)), float(m.group(4)), float(m.group(5))]
    return out


# ---------------------------------------------------------------- contact solve (Phase 2 femcontact.solve)
def solve(dofs, K, f, itf, kc=1.0e5, max_it=200, excluded=()):
    pos = {d: i for i, d in enumerate(dofs)}
    nodes = sorted({d[0] for d in dofs})
    rows = np.array([[pos[(nd, 1)], pos[(nd, 2)], pos[(nd, 3)]] for nd in nodes])
    g0 = np.array([itf[nd]["g0"] if nd not in excluded else 1e9 for nd in nodes])
    Nn = np.array([itf[nd]["n"] for nd in nodes])
    kinds = np.array([itf[nd]["kind"] for nd in nodes])
    act = g0 <= 1e-9
    hist = []
    for k in range(max_it):
        A = K.copy(); b = f.copy()
        for i in np.nonzero(act)[0]:
            r = rows[i]; nv = Nn[i]
            A[np.ix_(r, r)] += kc * np.outer(nv, nv)
            b[r] -= kc * g0[i] * nv
        u = np.linalg.solve(A, b)
        g = g0 + np.einsum("ij,ij->i", Nn, u[rows])
        new = g < 0
        hist.append((k, int(act.sum()), int(new.sum()), float(g.min())))
        if np.array_equal(new, act):
            break
        act = new
    else:
        raise RuntimeError("contact active set did not converge")
    lam = np.where(g < 0, -kc * g, 0.0)
    return dict(u=u, U=u[rows], g=g, lam=lam, nodes=nodes, rows=rows, normals=Nn, kinds=kinds, iterations=len(hist), hist=hist,
                max_penetration=float(-min(0.0, g.min())), excluded=np.array([nd in excluded for nd in nodes]))


def rigid_motion(res, itf):
    X = np.array([itf[n]["xyz"] for n in res["nodes"]]); U = res["U"]
    c = X.mean(0)
    A, b = [], []
    for x, u in zip(X - c, U):
        A.append([1, 0, 0, 0, x[2], -x[1]]); b.append(u[0])
        A.append([0, 1, 0, -x[2], 0, x[0]]); b.append(u[1])
        A.append([0, 0, 1, x[1], -x[0], 0]); b.append(u[2])
    s = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)[0]
    return dict(translation_mm=s[:3].tolist(), rotation_rad=s[3:].tolist(), centre_mm=c.tolist(),
                rotation_deg_about_xyz=np.degrees(s[3:]).round(4).tolist())


def rigid_disp_at(rm, p):
    t, w, c = np.array(rm["translation_mm"]), np.array(rm["rotation_rad"]), np.array(rm["centre_mm"])
    return t + np.cross(w, np.array(p) - c)


def contact_report(res, itf, P):
    out = {}
    for kind, lab in (("cyl", "saddle-cylinder"), ("tube", "sleeve-tube")):
        m = res["kinds"] == kind
        lam, g = res["lam"][m], res["g"][m]
        nodes = np.array(res["nodes"])[m]
        xyz = np.array([itf[n]["xyz"] for n in nodes])
        Fv = (res["normals"][m] * lam[:, None]).sum(0)
        act = lam > 0
        r = dict(nodes=int(m.sum()), nodes_in_contact=int(act.sum()), force_on_shelf_N=Fv.round(3).tolist(),
                 force_magnitude_N=round(float(np.linalg.norm(Fv)), 3),
                 max_open_gap_mm=round(float(g[~res["excluded"][m]].max()), 4))
        area = np.array([itf[n]["area"] for n in nodes])
        if act.any():
            p = lam / area
            r["max_nodal_pressure_MPa"] = round(float(p.max()), 3)
            r["contact_area_mm2"] = round(float(area[act].sum()), 1)
            r["centre_of_force_mm"] = np.average(xyz[act], axis=0, weights=lam[act]).round(2).tolist()
        if kind == "cyl":
            ang = np.degrees(np.arctan2(xyz[:, 0] - P["SaddleAxisX"], xyz[:, 2] - P["SaddleAxisZ"]))
            if act.any():
                r["contact_angle_range_deg(0=crown,+X)"] = [round(float(ang[act].min()), 1), round(float(ang[act].max()), 1)]
                r["contact_y_range_mm"] = [round(float(xyz[act, 1].min()), 1), round(float(xyz[act, 1].max()), 1)]
            bins = {}
            for lo, hi in ((-110, -60), (-60, -20), (-20, 20), (20, 60), (60, 110)):
                mm = (ang >= lo) & (ang < hi)
                bins["%d..%d" % (lo, hi)] = round(float(lam[mm].sum()), 2)
            r["normal_force_by_angle_band_N"] = bins
            crown = np.abs(ang) < 10
            r["crown_gap_max_mm(|angle|<10)"] = round(float(g[crown].max()), 4) if crown.any() else None
        else:
            ang = np.degrees(np.arctan2(xyz[:, 1] - P["SleeveY"], xyz[:, 0] - P["SleeveX"]))
            if act.any():
                r["contact_angle_range_deg(0=+X,90=+Y)"] = [round(float(ang[act].min()), 1), round(float(ang[act].max()), 1)]
                r["contact_z_range_mm"] = [round(float(xyz[act, 2].min()), 2), round(float(xyz[act, 2].max()), 2)]
            zb = {}
            for lo, hi in ((-25.0, -12.7), (-12.7, 0.0), (0.0, 12.7), (12.7, 26.0)):
                mm = (xyz[:, 2] >= lo) & (xyz[:, 2] < hi)
                zb["z %.1f..%.1f mm" % (lo, hi)] = round(float(lam[mm].sum()), 2)
            r["normal_force_by_height_N"] = zb
        out[lab] = r
    return out


# ---------------------------------------------------------------- ccx runner
def ccx(cfg, d, job, wait=True):
    env = dict(os.environ)
    for k in ("OMP_NUM_THREADS", "CCX_NPROC_EQUATION_SOLVER", "CCX_NPROC_STIFFNESS", "CCX_NPROC_RESULTS"):
        env[k] = str(cfg["threads"])
    lg = open(os.path.join(d, job + ".log"), "w")
    p = subprocess.Popen([cfg["ccx_exe"], "-i", job], cwd=d, stdout=lg, stderr=subprocess.STDOUT, env=env,
                         creationflags=0x08000000 if os.name == "nt" else 0)
    if wait:
        p.wait(); lg.close()
        return p.returncode
    return p


def finished(d, job):
    t = open(os.path.join(d, job + ".log"), errors="ignore").read()
    return "Job finished" in t, [l.strip() for l in t.splitlines() if re.search(r"warning|\*ERROR", l, re.I)][:10]


# ---------------------------------------------------------------- active-set route on the full model (Phase 3B)
def write_iter(path, Mo, itf, P, clr_s, mat, loads, active, kc):
    """Linear run = one semismooth-Newton step of the Phase 2 penalty contact problem on the full model.
    Each ACTIVE interface node i gets an axial spring (SPRINGA, stiffness kc) to a fixed ground node placed
    5 mm along -n_i, plus a constant nodal force -kc*g0_i*n_i; the spring force is then
    -kc*(n_i.u_i) n_i, so the total contact force is lambda_i n_i with lambda_i = -kc*(g0_i + n_i.u_i)."""
    L = []; w = L.append
    sp = _base(w, Mo, mat)
    nodes = sorted(itf)
    _nset(w, "IFACE", nodes); _nset(w, "N_SPRINGS", sp)
    act = sorted(active)
    g0n = int(max(Mo["nid"])) + 1000
    eid = len(Mo["E"]) + 100
    if act:
        w("*NODE, NSET=NGROUND")
        gid = {}
        for k, n in enumerate(act):
            x = np.array(itf[n]["xyz"]) - 5.0 * itf[n]["n"]
            gid[n] = g0n + k
            w("%d, %.6f, %.6f, %.6f" % (gid[n], x[0], x[1], x[2]))
        w("*ELEMENT, TYPE=SPRINGA, ELSET=ECONT")
        for n in act:
            w("%d, %d, %d" % (eid, n, gid[n])); eid += 1
        w("*SPRING, ELSET=ECONT"); w(""); w("%.6E" % kc)
    w("*STEP"); w("*STATIC")
    if act:
        w("*BOUNDARY"); w("NGROUND, 1, 3, 0.0")
    applied, pr = _loads(w, Mo, loads)
    if act:
        w("*CLOAD")
        for n in act:
            f = -kc * itf[n]["g0"] * itf[n]["n"]
            for k in range(3):
                if abs(f[k]) > 0:
                    w("%d, %d, %.10E" % (n, k + 1, f[k]))
    w("*NODE FILE, NSET=NALL"); w("U")
    w("*EL FILE"); w("S")
    w("*NODE PRINT, NSET=IFACE"); w("U")
    w("*NODE PRINT, NSET=N_SPRINGS"); w("U")
    w("*END STEP")
    open(path, "w").write("\n".join(L) + "\n")
    return dict(applied_N=applied, spring_nodes=sp, pressures=pr)


def active_set_full(cfg, W, Mo, itf, P, clr_s, mat, loads, excluded=(), seed=None, fh=None, tag=""):
    kc = cfg.get("kc_N_per_mm", 1e5)
    nodes = sorted(itf)
    g0 = np.array([itf[n]["g0"] for n in nodes])
    exm = np.array([n in excluded for n in nodes])
    act = set(n for n, g in zip(nodes, g0) if g <= 1e-9 and n not in excluded)
    if seed is not None:
        X = np.array([itf[n]["xyz"] for n in nodes]); sx = seed["xyz"][seed["lam"] > 0]
        if len(sx):
            d = np.min(((X[:, None, :] - sx[None, :, :]) ** 2).sum(-1), axis=1) ** 0.5
            act |= set(n for n, dd, e in zip(nodes, d, exm) if dd < cfg.get("seed_radius_mm", 2.5) and not e)
    resume = os.path.join(W, "active_set.json")
    if os.path.exists(resume):
        act = set(json.load(open(resume))) - set(excluded)
    hist = []; sets = []; cycle_fix = None; pending_break = False
    for it in range(cfg.get("max_active_set_iterations", 40)):
        json.dump(sorted(int(n) for n in act), open(resume, "w"))
        info = write_iter(os.path.join(W, "contact.inp"), Mo, itf, P, clr_s, mat, loads, act, kc)
        t = time.time()
        ccx(cfg, W, "contact")
        ok, warn = finished(W, "contact")
        if not ok:
            raise RuntimeError("contact iteration %d failed: %s" % (it, warn))
        ur = read_node_print(os.path.join(W, "contact.dat"))["IFACE"]
        g = g0 + np.array([np.dot(itf[n]["n"], ur[n]) for n in nodes])
        new = set(n for n, gg, e in zip(nodes, g, exm) if gg < 0 and not e)
        hist.append(dict(iteration=it, active_before=len(act), penetrating_after=len(new), changed=len(new ^ act),
                         min_gap_mm=round(float(g[~exm].min()), 5), ccx_s=round(time.time() - t, 1)))
        S.log("%s: active-set iteration %d: %d active -> %d penetrating (%d changed), min gap %.4f mm, %.0f s"
              % (tag, it, len(act), len(new), len(new ^ act), g[~exm].min(), time.time() - t), fh)
        if new == act or pending_break:
            break
        # 2-cycle (A -> B -> A) on a few nodes with ~zero contact force: take the smaller set
        # (no tensile contact; the dropped nodes penetrate by < max(|min gap|)), run it once, accept
        if len(sets) >= 1 and new == sets[-1] and len(new ^ act) <= cfg.get("cycle_max_nodes", 3):
            fix = new & act
            cycle_fix = dict(iteration=it, nodes_flipping=sorted(int(n) for n in (new ^ act)),
                             gaps_mm=[round(float(g[nodes.index(n)]), 6) for n in sorted(new ^ act)])
            S.log("%s: 2-cycle on %d node(s) %s -> accepting the smaller set" % (tag, len(new ^ act), cycle_fix["gaps_mm"]), fh)
            if fix == act:
                break
            sets.append(act); act = fix; pending_break = True
            continue
        sets.append(act)
        act = new
    else:
        raise RuntimeError("active set did not converge")
    # final state: global displacements from the .frd (authoritative), gaps and forces
    frd = S.read_frd(os.path.join(W, "contact.frd"))
    di = {n: i for i, n in enumerate(frd["res"]["DISP"][0])}
    U = np.array([frd["res"]["DISP"][1][di[n]][:3] for n in nodes])
    Nn = np.array([itf[n]["n"] for n in nodes])
    gg = g0 + np.einsum("ij,ij->i", Nn, U)
    actm = np.array([n in act for n in nodes])
    lam = np.where(actm, -kc * gg, 0.0)
    res = dict(nodes=nodes, U=U, g=np.where(exm, np.nan, gg), lam=lam, normals=Nn,
               kinds=np.array([itf[n]["kind"] for n in nodes]), excluded=exm, iterations=len(hist), hist=hist,
               max_penetration=float(-min(0.0, np.nanmin(np.where(exm, np.nan, gg)))),
               local_vs_global_gap_max_diff_mm=float(np.max(np.abs(gg - g))),
               tension_at_active_nodes=int((lam < 0).sum()), cycle_fix=cycle_fix)
    return res, frd, info


# ---------------------------------------------------------------- driver
def run_model(cfg, m, root, fh):
    tag = m["tag"]
    W = os.path.join(root, cfg["work_dir"], "runs", tag); os.makedirs(W, exist_ok=True)
    RES = os.path.join(root, cfg["work_dir"], "results"); os.makedirs(RES, exist_ok=True)
    T = {}
    t0 = time.time()
    shelf, P, finfo = S.load_model(os.path.join(root, m["fcstd"]))
    shelf_i = S.imprint_rings(shelf, P, cfg["loads"])
    groups = S.classify_faces(shelf_i, P, cfg["loads"])
    shelf_i.exportBrep(os.path.join(W, tag + ".brep"))
    S.write_geo(os.path.join(W, tag + ".geo"), tag + ".brep", groups, P, cfg["mesh"])
    T["geometry_s"] = round(time.time() - t0, 1)
    t1 = time.time()
    with open(os.path.join(W, tag + "_gmsh.log"), "w") as lg:
        r = subprocess.run([cfg["gmsh_exe"], tag + ".geo", "-format", "msh22", "-nt", str(cfg["mesh"].get("threads", 1)), "-"],
                           cwd=W, stdout=lg, stderr=subprocess.STDOUT)
    if r.returncode:
        raise RuntimeError("gmsh failed")
    T["meshing_s"] = round(time.time() - t1, 1)
    t2 = time.time()
    Mo = S.build_model(os.path.join(W, tag + ".msh"))
    q = S.mesh_quality(Mo)
    clr_s = P["SaddleClr"]; clr_t = P["SleeveTubeClr"] / 2
    itf = interface(Mo, P, clr_s, clr_t)
    ret = sorted(itf)
    mat = cfg["material"]
    method = cfg.get("method", "active_set_full")
    T["decks_s"] = round(time.time() - t2, 1)
    S.log("%s: mesh %d el / %d nodes (q_mean %.3f), interface %d nodes; geometry %.0f s, mesh %.0f s; method %s"
          % (tag, q["elements"], q["nodes"], q["q_mean"], len(ret), T["geometry_s"], T["meshing_s"], method), fh)
    if method == "condensed":
        write_subgen(os.path.join(W, "subgen.inp"), Mo, ret, mat)
        write_static(os.path.join(W, "fixed_interface.inp"), Mo, ret, mat, cfg["loads"])
        t3 = time.time()
        p1 = ccx(cfg, W, "subgen", wait=False); p2 = ccx(cfg, W, "fixed_interface", wait=False)
        p1.wait(); p2.wait()
        T["ccx_substructure_and_fixed_s"] = round(time.time() - t3, 1)
        for j in ("subgen", "fixed_interface"):
            ok, warn = finished(W, j)
            if not ok:
                raise RuntimeError("%s did not finish: %s" % (j, warn))
        t4 = time.time()
        dofs, K = read_kred(os.path.join(W, "subgen_K.mtx"))
        rf = read_node_print(os.path.join(W, "fixed_interface.dat"))["RET"]
        f = np.array([-rf[nd][k - 1] for nd, k in dofs])
        T["read_matrix_s"] = round(time.time() - t4, 1)
    out_all = {}
    variants = m.get("variants", [{"name": tag}])
    for v in variants:
        vt = v["name"]
        t5 = time.time()
        excl = set()
        if v.get("tube_zmax_in") is not None:
            excl = {n for n in ret if itf[n]["kind"] == "tube" and itf[n]["xyz"][2] > v["tube_zmax_in"] * IN + 1e-6}
        jd = os.path.join(W, vt); os.makedirs(jd, exist_ok=True)
        if method == "condensed":
            res = solve(dofs, K, f, itf, kc=cfg.get("kc_N_per_mm", 1e5), excluded=excl)
            T_solve = round(time.time() - t5, 1)
            un = {nd: res["u"][res["rows"][i]] for i, nd in enumerate(res["nodes"])}
            info = write_static(os.path.join(jd, "final.inp"), Mo, ret, mat, cfg["loads"], prescribed=un)
            t6 = time.time()
            ccx(cfg, jd, "final")
            T_final = round(time.time() - t6, 1)
            ok, warn = finished(jd, "final")
            if not ok:
                raise RuntimeError("final run %s failed %s" % (vt, warn))
            t7 = time.time()
            frd = S.read_frd(os.path.join(jd, "final.frd")); datf = os.path.join(jd, "final.dat")
        else:
            seed = None
            if v.get("seed_npz") and os.path.exists(os.path.join(root, v["seed_npz"])):
                seed = dict(np.load(os.path.join(root, v["seed_npz"])))
            res, frd, info = active_set_full(cfg, jd, Mo, itf, P, clr_s, mat, cfg["loads"], excluded=excl, seed=seed, fh=fh, tag=vt)
            T_solve = round(time.time() - t5, 1); T_final = 0.0
            ok, warn = finished(jd, "contact"); t7 = time.time(); datf = os.path.join(jd, "contact.dat")
        rep = contact_report(res, itf, P)
        rm = rigid_motion(res, itf)
        rep["rigid_fit_of_interface"] = {k: (np.round(v_, 5).tolist() if isinstance(v_, list) else v_) for k, v_ in rm.items()}
        rep["active_set_iterations"] = res["iterations"]
        rep["active_set_history"] = res["hist"] if method != "condensed" else [list(h) for h in res["hist"]]
        rep["max_penetration_mm"] = round(res["max_penetration"], 6)
        rep["tube_nodes_excluded_from_contact"] = len(excl)
        if method != "condensed":
            rep["local_vs_global_gap_check_max_diff_mm"] = res["local_vs_global_gap_max_diff_mm"]
            rep["active_nodes_in_tension"] = res["tension_at_active_nodes"]
            rep["cycle_fix"] = res["cycle_fix"]
        summ, surf = S.summarize(frd, Mo, P, cfg, info)
        # equilibrium and contact-force check
        npr = read_node_print(datf)
        Uspr = npr.get("N_SPRINGS", {})
        Fs = sum((np.abs(u) * SPRING_K for u in Uspr.values()), np.zeros(3))
        Wshelf = mat["rho_t_mm3"] * q["volume_mm3"] * G_MM
        Fc = (res["normals"] * res["lam"][:, None]).sum(0)
        eq = dict(applied_external_N=round(info["applied_N"], 4), shelf_self_weight_N=round(Wshelf, 4),
                  expected_total_down_N=round(info["applied_N"] + Wshelf, 4), contact_force_sum_on_shelf_N=Fc.round(4).tolist(),
                  error_pct=round(100 * abs(Fc[2] - info["applied_N"] - Wshelf) / (info["applied_N"] + Wshelf), 4),
                  stabilisation_spring_force_max_N=round(float(np.max(Fs)) if len(Uspr) else 0.0, 6))
        if method == "condensed":
            tot = read_totals(datf); Fr = np.array(tot.get("RET", [0, 0, 0])); rfn = npr["RET"]
            eq["interface_reaction_sum_N"] = Fr.round(4).tolist()
            eq["max_node_reaction_minus_contact_force_N"] = round(float(max(np.linalg.norm(rfn[nd] - res["normals"][i] * res["lam"][i])
                                                                      for i, nd in enumerate(res["nodes"]))), 6)
        summ["equilibrium"] = eq
        # extra installed-condition metrics
        X, U = surf["X"], surf["U"]
        k3 = cfg["loads"]["pump_bottle"]
        bc = np.array([P["Bottle%dX" % k3], P["BottleY"], P["FloorTopZ"]])
        sel = (np.hypot(X[:, 0] - bc[0], X[:, 1] - bc[1]) < 1.30 * IN) & (np.abs(X[:, 2] - bc[2]) < 0.01) & \
              (np.hypot(X[:, 0] - bc[0], X[:, 1] - bc[1]) > 1.00 * IN)
        A = np.c_[X[sel, 0] - bc[0], X[sel, 1] - bc[1], np.ones(sel.sum())]
        cxy = np.linalg.lstsq(A, U[sel, 2], rcond=None)[0]
        summ["bottle%d_centre_Uz_planefit_mm" % k3] = round(float(cxy[2]), 4)
        lw = (X[:, 0] < P["SleeveX"] - 1.0 * IN) & (X[:, 2] > -0.10 * IN)
        il = np.nonzero(lw)[0][U[lw, 2].argmin()]
        summ["left_rim_max_down_mm"] = round(float(-U[il, 2]), 4); summ["left_rim_max_down_at_mm"] = X[il].round(1).tolist()
        rb = rigid_disp_at(rm, bc)
        summ["rigid_mount_motion_at_bottle%d_centre_mm" % k3] = rb.round(4).tolist()
        summ["elastic_part_bottle%d_centre_Uz_mm" % k3] = round(float(cxy[2] - rb[2]), 4)
        summ["contact"] = rep
        summ["timing_s"] = dict(T, contact_solve_s=T_solve, final_ccx_s=T_final, post_s=round(time.time() - t7, 1),
                                variant_total_s=round(time.time() - t5, 1))
        summ["model"] = dict(tag=tag, variant=vt, file=m["fcstd"], sha256_16=finfo["sha256_16"],
                             volume_in3=round(finfo["volume_mm3"] / IN ** 3, 4), sleeve_top_Z_in=round(P["SleeveTopZ"] / IN, 4),
                             tube_contact_zmax_in=v.get("tube_zmax_in"))
        summ["mesh"] = q; summ["solver"] = dict(method=method, final_finished=ok, warnings=warn, kc=cfg.get("kc_N_per_mm", 1e5),
                                               interface_nodes=len(ret), interface_dofs=3 * len(ret))
        json.dump(summ, open(os.path.join(RES, vt + "_contact_summary.json"), "w"), indent=1, default=float)
        if os.environ.get("FREECAD_JOURNAL_PROJECT"):
            _journal_bridge().record_fem("contact", summ,
                os.path.join(RES, vt + "_contact_summary.json"),
                cfg.get("_journal_config_path"), os.path.join(root, m["fcstd"]))
        np.savez_compressed(os.path.join(RES, vt + "_surface.npz"), **surf)
        xyz = np.array([itf[n]["xyz"] for n in res["nodes"]])
        area = np.array([itf[n]["area"] for n in res["nodes"]])
        ang = np.where(res["kinds"] == "cyl", np.degrees(np.arctan2(xyz[:, 0] - P["SaddleAxisX"], xyz[:, 2] - P["SaddleAxisZ"])),
                       np.degrees(np.arctan2(xyz[:, 1] - P["SleeveY"], xyz[:, 0] - P["SleeveX"])))
        np.savez_compressed(os.path.join(RES, vt + "_contact_nodes.npz"), xyz=xyz, lam=res["lam"], g=res["g"], ang=ang,
                            p=res["lam"] / area, kinds=res["kinds"], excluded=res["excluded"])
        S.log("%s: contact %d it (%.0f s), final run %.0f s; B%d centre Uz %.3f mm (rigid %.3f), max down %.3f, roll %.3f deg, eq %.4f %%"
              % (vt, res["iterations"], T_solve, T_final, k3, cxy[2], rb[2], summ["max_down_disp_mm"],
                 rm["rotation_deg_about_xyz"][1], summ["equilibrium"]["error_pct"]), fh)
        out_all[vt] = summ
    return out_all


def plot_contact(cfg, root, tags):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    RES = os.path.join(root, cfg["work_dir"], "results"); IMG = os.path.join(root, cfg["work_dir"], "images")
    os.makedirs(IMG, exist_ok=True)
    fig, axs = plt.subplots(2, len(tags), figsize=(6.2 * len(tags), 8.5), dpi=120, squeeze=False)
    pmax = 0
    D = {t: np.load(os.path.join(RES, t + "_contact_nodes.npz")) for t in tags}
    for t in tags:
        pmax = max(pmax, float(np.percentile(D[t]["p"][D[t]["p"] > 0], 98)) if (D[t]["p"] > 0).any() else 0)
    for j, t in enumerate(tags):
        d = D[t]; k = d["kinds"]; x = d["xyz"]; p = d["p"]
        s = json.load(open(os.path.join(RES, t + "_contact_summary.json")))
        for i, (kind, lab) in enumerate((("cyl", "saddle"), ("tube", "sleeve bore"))):
            ax = axs[i, j]; m = k == kind
            if kind == "cyl":
                X_, Y_ = d["ang"][m], x[m, 1]; ax.set_xlabel("angle from crown [deg] (+ = +X / one-bottle side)"); ax.set_ylabel("Y [mm]")
            else:
                X_, Y_ = d["ang"][m], x[m, 2]; ax.set_xlabel("angle about sleeve axis [deg] (0 = +X, 90 = +Y front)"); ax.set_ylabel("Z [mm]")
            pm = p[m]; act = pm > 0
            ax.scatter(X_[~act], Y_[~act], s=3, c="#cccccc", label="open (separated)")
            sc = ax.scatter(X_[act], Y_[act], s=9, c=pm[act], cmap="inferno_r", vmin=0, vmax=max(pmax, 1e-6), label="in contact")
            if kind == "tube" and d["excluded"][m].any():
                ax.scatter(X_[d["excluded"][m]], Y_[d["excluded"][m]], s=3, c="#9ecae1", label="excluded (V3 height variant)")
            F = s["contact"]["saddle-cylinder" if kind == "cyl" else "sleeve-tube"]
            ax.set_title("%s - %s: |F| %.0f N, %d/%d nodes in contact" % (t, lab, F["force_magnitude_N"], F["nodes_in_contact"], F["nodes"]), fontsize=9)
            ax.legend(fontsize=7, loc="upper right")
            plt.colorbar(sc, ax=ax, label="nodal contact pressure [MPa]")
    fig.suptitle("Contact status at the mount (case B, 10 lbf): grey = separated, coloured = in contact", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(IMG, "contact_maps.png")); plt.close(fig)


def main(config_path):
    cfg = json.load(open(config_path))
    cfg["_journal_config_path"] = os.path.abspath(config_path)
    root = cfg["project_dir"]
    wd = os.path.join(root, cfg["work_dir"]); os.makedirs(wd, exist_ok=True)
    fh = open(os.path.join(wd, "contact_log.txt"), "a")
    S.log("=== ShowerShelf_FEM_Contact %s" % VERSION, fh)
    S.log("versions: calculix %s, gmsh %s" % (S.tool_version(cfg["ccx_exe"], ["-v"]), S.tool_version(cfg["gmsh_exe"], ["--version"])), fh)
    T0 = time.time()
    only = [x for x in os.environ.get("SHELF_CONTACT_ONLY", "").split(",") if x]
    allv = []
    for m in cfg["models"]:
        if only and m["tag"] not in only:
            allv += [v["name"] for v in m.get("variants", [{"name": m["tag"]}])]
            continue
        t = time.time()
        run_model(cfg, m, root, fh)
        S.log("%s: model total %.0f s" % (m["tag"], time.time() - t), fh)
        allv += [v["name"] for v in m.get("variants", [{"name": m["tag"]}])]
    # plots
    t = time.time()
    RES = os.path.join(root, cfg["work_dir"], "results"); IMG = os.path.join(root, cfg["work_dir"], "images")
    os.makedirs(IMG, exist_ok=True)
    tags = [v for v in allv if os.path.exists(os.path.join(RES, v + "_surface.npz"))]
    Fs = {v: dict(np.load(os.path.join(RES, v + "_surface.npz"))) for v in tags}
    umin = min(float(Fs[v]["U"][:, 2].min()) for v in tags); umax = max(float(Fs[v]["U"][:, 2].max()) for v in tags)
    for p in cfg["plots"]:
        sel = [v for v in p.get("tags", tags) if v in tags]
        if p["field"] == "Uz":
            lo, hi = umin, max(umax, 0.0)
        elif p["field"] == "Utot":
            lo, hi = 0.0, max(float(np.linalg.norm(Fs[v]["U"], axis=1).max()) for v in sel)
        else:
            lo, hi = p["range"]
        S.plot_compare([Fs[v] for v in sel], sel, p["field"], p["view"], os.path.join(IMG, p["file"]), lo, hi, p["title"],
                       crop_in=p.get("crop_in"), note=p.get("note", ""))
    plot_contact(cfg, root, tags)
    S.log("plots %.0f s; total %.0f s" % (time.time() - t, time.time() - T0), fh)
    fh.close()


if (__name__ == "__main__" or os.environ.get("SHELF_CONTACT_RUN") == "1") and not os.environ.get("_SHELF_CONTACT_ACTIVE"):
    os.environ["_SHELF_CONTACT_ACTIVE"] = "1"
    main(os.environ.get("SHELF_CONTACT_CONFIG") or os.path.join(HERE, "FEM_Contact_config.json"))

# Optional engineering journal bridge; set FREECAD_JOURNAL_PROJECT to enable.
def _journal_bridge():
    import os, sys
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path: sys.path.insert(0, parent)
    import journal_integration
    return journal_integration
